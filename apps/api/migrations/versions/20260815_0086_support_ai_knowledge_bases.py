"""Make knowledge bases first-class, agent-owned scopes for support AI.

One knowledge base belongs to exactly one (store, agent) scope.  An agent may
own many knowledge bases; uploaded files and training material are attached to
one knowledge base.  Legacy rows are re-parented to one generated default base
per bound store and agent.

Revision ID: 20260815_0086
Revises: 20260814_0085
"""

from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op


revision = "20260815_0086"
down_revision = "20260814_0085"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def _raw_uuid(value: UUID) -> UUID | str:
    return value if op.get_bind().dialect.name == "postgresql" else value.hex


def _default_name(
    bind: sa.Connection,
    *,
    tenant_id: object,
    agent_id: object,
    tenant_name: str,
    agent_name: str,
) -> str:
    base = f"{tenant_name} · {agent_name}知识库".strip()[:160]
    existing = {
        str(row[0])
        for row in bind.execute(
            sa.text(
                "SELECT name FROM support_ai_knowledge_bases "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id"
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        ).all()
    }
    if base not in existing:
        return base
    for index in range(2, 1000):
        candidate = f"{base[: max(1, 156 - len(str(index)))]} {index}"
        if candidate not in existing:
            return candidate
    raise RuntimeError("could not allocate a knowledge base name")


def _add_nullable_fk_column(
    table_name: str,
    column_name: str,
    *,
    foreign_table: str,
    foreign_column: str = "id",
    index_name: str,
    constraint_name: str,
) -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns(table_name)}
    if column_name in columns:
        return
    with op.batch_alter_table(table_name) as batch:
        batch.add_column(sa.Column(column_name, U(), nullable=True))
        batch.create_foreign_key(
            constraint_name,
            foreign_table,
            [column_name],
            [foreign_column],
            ondelete="CASCADE",
        )
        batch.create_index(index_name, [column_name])


def _replace_training_unique_constraints(*, offline: bool = False) -> None:
    """Make training identifiers and versions unique inside a KB scope."""

    constraints = (
        (
            "support_ai_training_cases",
            "uq_support_ai_training_cases_external",
            "uq_support_ai_training_cases_knowledge_base_external",
            ["agent_id", "knowledge_base_id", "external_id"],
        ),
        (
            "support_ai_training_rules",
            "uq_support_ai_training_rules_key",
            "uq_support_ai_training_rules_knowledge_base_key",
            ["agent_id", "knowledge_base_id", "rule_key"],
        ),
        (
            "support_ai_training_versions",
            "uq_support_ai_training_versions_number",
            "uq_support_ai_training_versions_knowledge_base_number",
            ["agent_id", "knowledge_base_id", "version_number"],
        ),
    )
    bind = None if offline else op.get_bind()
    for table_name, old_name, new_name, columns in constraints:
        if offline:
            with op.batch_alter_table(table_name) as batch:
                batch.drop_constraint(old_name, type_="unique")
                batch.create_unique_constraint(new_name, columns)
            continue
        existing = {
            item.get("name")
            for item in sa.inspect(bind).get_unique_constraints(table_name)
        }
        with op.batch_alter_table(table_name) as batch:
            if old_name in existing:
                batch.drop_constraint(old_name, type_="unique")
            if new_name not in existing:
                batch.create_unique_constraint(new_name, columns)


def upgrade() -> None:
    if op.get_context().as_sql:
        # Offline PostgreSQL generation has no inspector.  Emit the canonical
        # 0085 -> 0086 DDL directly; online mode below additionally performs
        # idempotent checks and legacy backfill.
        op.create_table(
            "support_ai_knowledge_bases",
            sa.Column("id", U(), nullable=False),
            sa.Column("tenant_id", U(), nullable=False),
            sa.Column("agent_id", U(), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            sa.Column("created_by_user_id", U(), nullable=False),
            sa.Column("updated_by_user_id", U(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_support_ai_knowledge_bases_status_allowed"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_support_ai_knowledge_bases_tenant", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["support_ai_agents.id"], name="fk_support_ai_knowledge_bases_agent", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_support_ai_knowledge_bases_created_by_user", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], name="fk_support_ai_knowledge_bases_updated_by_user", ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_support_ai_knowledge_bases"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_support_ai_knowledge_bases_tenant_identity"),
            sa.UniqueConstraint("tenant_id", "agent_id", "name", name="uq_support_ai_knowledge_bases_tenant_agent_name"),
        )
        op.create_index(
            "ix_support_ai_knowledge_bases_tenant_agent_status",
            "support_ai_knowledge_bases",
            ["tenant_id", "agent_id", "status", "updated_at"],
        )
        op.add_column("support_ai_knowledge_sources", sa.Column("knowledge_base_id", U(), nullable=True))
        op.create_foreign_key(
            "fk_support_ai_knowledge_sources_tenant_knowledge_base",
            "support_ai_knowledge_sources",
            "support_ai_knowledge_bases",
            ["tenant_id", "knowledge_base_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        op.create_index("ix_support_ai_knowledge_sources_knowledge_base_id", "support_ai_knowledge_sources", ["knowledge_base_id"])
        for table_name, constraint_name, index_name in (
            ("support_ai_training_cases", "fk_support_ai_training_cases_knowledge_base", "ix_support_ai_training_cases_knowledge_base_id"),
            ("support_ai_training_rules", "fk_support_ai_training_rules_knowledge_base", "ix_support_ai_training_rules_knowledge_base_id"),
            ("support_ai_training_versions", "fk_support_ai_training_versions_knowledge_base", "ix_support_ai_training_versions_knowledge_base_id"),
        ):
            op.add_column(table_name, sa.Column("knowledge_base_id", U(), nullable=True))
            op.create_foreign_key(constraint_name, table_name, "support_ai_knowledge_bases", ["knowledge_base_id"], ["id"], ondelete="CASCADE")
            op.create_index(index_name, table_name, ["knowledge_base_id"])
        _replace_training_unique_constraints(offline=True)
        op.drop_index("uq_support_ai_training_versions_active_agent", table_name="support_ai_training_versions")
        op.create_index(
            "uq_support_ai_training_versions_active_knowledge_base",
            "support_ai_training_versions",
            ["knowledge_base_id"],
            unique=True,
            postgresql_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NOT NULL"),
            sqlite_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NOT NULL"),
        )
        op.create_index(
            "uq_support_ai_training_versions_active_legacy_agent",
            "support_ai_training_versions",
            ["agent_id"],
            unique=True,
            postgresql_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NULL"),
            sqlite_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NULL"),
        )
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("support_ai_knowledge_bases"):
        op.create_table(
            "support_ai_knowledge_bases",
            sa.Column("id", U(), nullable=False),
            sa.Column("tenant_id", U(), nullable=False),
            sa.Column("agent_id", U(), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            sa.Column("created_by_user_id", U(), nullable=False),
            sa.Column("updated_by_user_id", U(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_support_ai_knowledge_bases_status_allowed"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_support_ai_knowledge_bases_tenant", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_id"], ["support_ai_agents.id"], name="fk_support_ai_knowledge_bases_agent", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_support_ai_knowledge_bases_created_by_user", ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], name="fk_support_ai_knowledge_bases_updated_by_user", ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_support_ai_knowledge_bases"),
            sa.UniqueConstraint("tenant_id", "id", name="uq_support_ai_knowledge_bases_tenant_identity"),
            sa.UniqueConstraint("tenant_id", "agent_id", "name", name="uq_support_ai_knowledge_bases_tenant_agent_name"),
        )
        op.create_index(
            "ix_support_ai_knowledge_bases_tenant_agent_status",
            "support_ai_knowledge_bases",
            ["tenant_id", "agent_id", "status", "updated_at"],
        )

    # A source uses a tenant+base composite key so a source cannot be pointed
    # at a base from another store.
    source_columns = {item["name"] for item in sa.inspect(bind).get_columns("support_ai_knowledge_sources")}
    if "knowledge_base_id" not in source_columns:
        with op.batch_alter_table("support_ai_knowledge_sources") as batch:
            batch.add_column(sa.Column("knowledge_base_id", U(), nullable=True))
            batch.create_foreign_key(
                "fk_support_ai_knowledge_sources_tenant_knowledge_base",
                "support_ai_knowledge_bases",
                ["tenant_id", "knowledge_base_id"],
                ["tenant_id", "id"],
                ondelete="CASCADE",
            )
            batch.create_index("ix_support_ai_knowledge_sources_knowledge_base_id", ["knowledge_base_id"])
    else:
        fk_names = {item.get("name") for item in sa.inspect(bind).get_foreign_keys("support_ai_knowledge_sources")}
        if "fk_support_ai_knowledge_sources_tenant_knowledge_base" not in fk_names:
            with op.batch_alter_table("support_ai_knowledge_sources") as batch:
                batch.create_foreign_key(
                    "fk_support_ai_knowledge_sources_tenant_knowledge_base",
                    "support_ai_knowledge_bases",
                    ["tenant_id", "knowledge_base_id"],
                    ["tenant_id", "id"],
                    ondelete="CASCADE",
                )

    # Training material may be legacy agent-wide (NULL) or explicitly scoped
    # to one base.  NULL remains a shared fallback for backwards compatibility.
    _add_nullable_fk_column(
        "support_ai_training_cases", "knowledge_base_id",
        foreign_table="support_ai_knowledge_bases",
        index_name="ix_support_ai_training_cases_knowledge_base_id",
        constraint_name="fk_support_ai_training_cases_knowledge_base",
    )
    _add_nullable_fk_column(
        "support_ai_training_rules", "knowledge_base_id",
        foreign_table="support_ai_knowledge_bases",
        index_name="ix_support_ai_training_rules_knowledge_base_id",
        constraint_name="fk_support_ai_training_rules_knowledge_base",
    )
    _add_nullable_fk_column(
        "support_ai_training_versions", "knowledge_base_id",
        foreign_table="support_ai_knowledge_bases",
        index_name="ix_support_ai_training_versions_knowledge_base_id",
        constraint_name="fk_support_ai_training_versions_knowledge_base",
    )
    _replace_training_unique_constraints()

    # Replace the legacy agent-wide active-version index.  NULL bases are not
    # collapsed by SQL UNIQUE semantics and therefore retain compatibility.
    index_names = {item["name"] for item in sa.inspect(bind).get_indexes("support_ai_training_versions")}
    if "uq_support_ai_training_versions_active_agent" in index_names:
        op.drop_index("uq_support_ai_training_versions_active_agent", table_name="support_ai_training_versions")
    if "uq_support_ai_training_versions_active_knowledge_base" not in index_names:
        op.create_index(
            "uq_support_ai_training_versions_active_knowledge_base",
            "support_ai_training_versions",
            ["knowledge_base_id"],
            unique=True,
            sqlite_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NOT NULL"),
            postgresql_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NOT NULL"),
        )
    if "uq_support_ai_training_versions_active_legacy_agent" not in index_names:
        op.create_index(
            "uq_support_ai_training_versions_active_legacy_agent",
            "support_ai_training_versions",
            ["agent_id"],
            unique=True,
            sqlite_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NULL"),
            postgresql_where=sa.text("status = 'PUBLISHED' AND knowledge_base_id IS NULL"),
        )

    # Backfill one default base for every currently bound store/agent scope.
    scopes = bind.execute(
        sa.text(
            "SELECT settings.tenant_id, settings.agent_id, tenants.name AS tenant_name, "
            "agents.name AS agent_name, settings.updated_by_user_id, agents.created_by_user_id "
            "FROM support_ai_settings AS settings "
            "JOIN tenants ON tenants.id = settings.tenant_id "
            "JOIN support_ai_agents AS agents ON agents.id = settings.agent_id "
            "WHERE settings.agent_id IS NOT NULL AND settings.deleted_at IS NULL "
            "AND tenants.deleted_at IS NULL"
        )
    ).mappings().all()
    fallback_user = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
    for scope in scopes:
        tenant_id = scope["tenant_id"]
        agent_id = scope["agent_id"]
        existing = bind.execute(
            sa.text(
                "SELECT id FROM support_ai_knowledge_bases "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        ).scalar()
        if existing is not None:
            knowledge_base_id = existing
        else:
            creator = scope["updated_by_user_id"] or scope["created_by_user_id"] or fallback_user
            if creator is None:
                continue
            generated_id = uuid4()
            knowledge_base_id = _raw_uuid(generated_id)
            name = _default_name(
                bind,
                tenant_id=tenant_id,
                agent_id=agent_id,
                tenant_name=str(scope["tenant_name"]),
                agent_name=str(scope["agent_name"]),
            )
            bind.execute(
                sa.text(
                    "INSERT INTO support_ai_knowledge_bases "
                    "(id, tenant_id, agent_id, name, status, created_by_user_id, updated_by_user_id) "
                    "VALUES (:id, :tenant_id, :agent_id, :name, 'ACTIVE', :created_by_user_id, :updated_by_user_id)"
                ),
                {"id": knowledge_base_id, "tenant_id": tenant_id, "agent_id": agent_id, "name": name, "created_by_user_id": creator, "updated_by_user_id": creator},
            )
        bind.execute(
            sa.text(
                "UPDATE support_ai_knowledge_sources SET knowledge_base_id = :knowledge_base_id "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id AND knowledge_base_id IS NULL"
            ),
            {"knowledge_base_id": knowledge_base_id, "tenant_id": tenant_id, "agent_id": agent_id},
        )


def downgrade() -> None:
    # Remove the partial index before SQLite rebuilds the table without the
    # scoped column; otherwise batch mode tries to recreate it mid-rebuild.
    op.drop_index(
        "uq_support_ai_training_versions_active_knowledge_base",
        table_name="support_ai_training_versions",
    )
    op.drop_index(
        "uq_support_ai_training_versions_active_legacy_agent",
        table_name="support_ai_training_versions",
    )
    for table_name, constraint_name in (
        ("support_ai_training_versions", "uq_support_ai_training_versions_knowledge_base_number"),
        ("support_ai_training_rules", "uq_support_ai_training_rules_knowledge_base_key"),
        ("support_ai_training_cases", "uq_support_ai_training_cases_knowledge_base_external"),
    ):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_constraint(constraint_name, type_="unique")
    with op.batch_alter_table("support_ai_training_versions") as batch:
        batch.drop_index("ix_support_ai_training_versions_knowledge_base_id")
        batch.drop_constraint("fk_support_ai_training_versions_knowledge_base", type_="foreignkey")
        batch.drop_column("knowledge_base_id")
    with op.batch_alter_table("support_ai_training_rules") as batch:
        batch.drop_index("ix_support_ai_training_rules_knowledge_base_id")
        batch.drop_constraint("fk_support_ai_training_rules_knowledge_base", type_="foreignkey")
        batch.drop_column("knowledge_base_id")
    with op.batch_alter_table("support_ai_training_cases") as batch:
        batch.drop_index("ix_support_ai_training_cases_knowledge_base_id")
        batch.drop_constraint("fk_support_ai_training_cases_knowledge_base", type_="foreignkey")
        batch.drop_column("knowledge_base_id")
    with op.batch_alter_table("support_ai_knowledge_sources") as batch:
        batch.drop_index("ix_support_ai_knowledge_sources_knowledge_base_id")
        batch.drop_constraint("fk_support_ai_knowledge_sources_tenant_knowledge_base", type_="foreignkey")
        batch.drop_column("knowledge_base_id")
    op.drop_index("ix_support_ai_knowledge_bases_tenant_agent_status", table_name="support_ai_knowledge_bases")
    op.drop_table("support_ai_knowledge_bases")
    with op.batch_alter_table("support_ai_training_cases") as batch:
        batch.create_unique_constraint(
            "uq_support_ai_training_cases_external", ["agent_id", "external_id"]
        )
    with op.batch_alter_table("support_ai_training_rules") as batch:
        batch.create_unique_constraint(
            "uq_support_ai_training_rules_key", ["agent_id", "rule_key"]
        )
    with op.batch_alter_table("support_ai_training_versions") as batch:
        batch.create_unique_constraint(
            "uq_support_ai_training_versions_number", ["agent_id", "version_number"]
        )
    op.create_index(
        "uq_support_ai_training_versions_active_agent",
        "support_ai_training_versions",
        ["agent_id"],
        unique=True,
        sqlite_where=sa.text("status = 'PUBLISHED'"),
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
