"""Introduce first-class knowledge bases for support AI agents.

Revision ID: 20260815_0087
Revises: 20260815_0086
"""

from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op


revision = "20260815_0087"
down_revision = "20260815_0086"
branch_labels = None
depends_on = None


U = lambda: sa.Uuid(as_uuid=True)


def _raw_uuid(value: UUID) -> UUID | str:
    """Adapt UUID values for raw SQL on SQLite and PostgreSQL."""

    return value if op.get_bind().dialect.name == "postgresql" else value.hex


def _knowledge_base_name(bind: sa.Connection, *, tenant_id: object, agent_id: object,
                         tenant_name: str, agent_name: str) -> str:
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


def upgrade() -> None:
    bind = op.get_bind()
    offline = op.get_context().as_sql
    inspector = None if offline else sa.inspect(bind)
    if offline or not inspector.has_table("support_ai_knowledge_bases"):
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
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                      server_default=sa.func.now()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('ACTIVE', 'DISABLED')",
                name="ck_support_ai_knowledge_bases_status_allowed",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"], ["tenants.id"],
                name="fk_support_ai_knowledge_bases_tenant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["agent_id"], ["support_ai_agents.id"],
                name="fk_support_ai_knowledge_bases_agent",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"], ["users.id"],
                name="fk_support_ai_knowledge_bases_created_by_user",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["updated_by_user_id"], ["users.id"],
                name="fk_support_ai_knowledge_bases_updated_by_user",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_support_ai_knowledge_bases"),
            sa.UniqueConstraint(
                "tenant_id", "id",
                name="uq_support_ai_knowledge_bases_tenant_identity",
            ),
            sa.UniqueConstraint(
                "tenant_id", "agent_id", "name",
                name="uq_support_ai_knowledge_bases_tenant_agent_name",
            ),
        )
        op.create_index(
            "ix_support_ai_knowledge_bases_tenant_agent_status",
            "support_ai_knowledge_bases",
            ["tenant_id", "agent_id", "status", "updated_at"],
        )

    source_columns = (
        set()
        if offline
        else {
            column["name"]
            for column in inspector.get_columns("support_ai_knowledge_sources")
        }
    )
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
            batch.create_index(
                "ix_support_ai_knowledge_sources_knowledge_base_id",
                ["knowledge_base_id"],
            )

    if offline:
        return

    # Existing installations stored files directly under (tenant, agent).
    # Give every such scope one default knowledge base and re-parent its files.
    scopes = bind.execute(
        sa.text(
            "SELECT settings.tenant_id, settings.agent_id, tenants.name AS tenant_name, "
            "agents.name AS agent_name, settings.updated_by_user_id, agents.created_by_user_id "
            "FROM support_ai_settings AS settings "
            "JOIN tenants ON tenants.id = settings.tenant_id "
            "JOIN support_ai_agents AS agents ON agents.id = settings.agent_id "
            "WHERE settings.agent_id IS NOT NULL "
            "AND settings.deleted_at IS NULL AND tenants.deleted_at IS NULL"
        )
    ).mappings().all()
    fallback_user = bind.execute(sa.text("SELECT id FROM users ORDER BY id LIMIT 1")).scalar()
    for scope in scopes:
        tenant_id = scope["tenant_id"]
        agent_id = scope["agent_id"]
        exists = bind.execute(
            sa.text(
                "SELECT id FROM support_ai_knowledge_bases "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND deleted_at IS NULL ORDER BY created_at LIMIT 1"
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        ).scalar()
        if exists is not None:
            continue
        creator = scope["updated_by_user_id"] or scope["created_by_user_id"] or fallback_user
        if creator is None:
            # A database without users cannot have usable admin-owned knowledge;
            # leave the scope for a later explicit create operation.
            continue
        knowledge_base_id = uuid4()
        knowledge_base_id_raw = _raw_uuid(knowledge_base_id)
        name = _knowledge_base_name(
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
                "VALUES (:id, :tenant_id, :agent_id, :name, 'ACTIVE', "
                ":created_by_user_id, :updated_by_user_id)"
            ),
            {
                "id": knowledge_base_id_raw,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "name": name,
                "created_by_user_id": creator,
                "updated_by_user_id": creator,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE support_ai_knowledge_sources SET knowledge_base_id = :knowledge_base_id "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND knowledge_base_id IS NULL"
            ),
            {
                "knowledge_base_id": knowledge_base_id_raw,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    foreign_key_names = {
        item.get("name")
        for item in sa.inspect(bind).get_foreign_keys("support_ai_knowledge_sources")
    }
    index_names = {
        item.get("name")
        for item in sa.inspect(bind).get_indexes("support_ai_knowledge_sources")
    }
    with op.batch_alter_table("support_ai_knowledge_sources") as batch:
        if "ix_support_ai_knowledge_sources_knowledge_base_id" in index_names:
            batch.drop_index("ix_support_ai_knowledge_sources_knowledge_base_id")
        for constraint_name in (
            "fk_support_ai_knowledge_sources_tenant_knowledge_base",
            "fk_support_ai_knowledge_sources_knowledge_base",
        ):
            if constraint_name in foreign_key_names:
                batch.drop_constraint(constraint_name, type_="foreignkey")
        batch.drop_column("knowledge_base_id")
    op.drop_index(
        "ix_support_ai_knowledge_bases_tenant_agent_status",
        table_name="support_ai_knowledge_bases",
    )
    op.drop_table("support_ai_knowledge_bases")
