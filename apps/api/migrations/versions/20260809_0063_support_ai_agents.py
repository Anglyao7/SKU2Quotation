"""Add platform-managed intelligent agents and store bindings.

Revision ID: 20260809_0063
Revises: 20260809_0062
"""

from __future__ import annotations

import secrets
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql


revision = "20260809_0063"
down_revision = "20260809_0062"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _database_uuid() -> UUID:
    # SQLAlchemy's portable Uuid type expects a UUID object on every dialect;
    # its SQLite bind processor performs the hexadecimal conversion itself.
    return uuid4()


def _raw_uuid(value: UUID) -> UUID | str:
    """Adapt a UUID used through raw SQL, which bypasses type bind processors."""

    if op.get_bind().dialect.name == "postgresql":
        return value
    return value.hex


def _agent_code(used: set[str]) -> str:
    for _attempt in range(100):
        value = str(secrets.randbelow(90_000_000) + 10_000_000)
        if value not in used:
            used.add(value)
            return value
    raise RuntimeError("could not allocate a unique support AI agent code")


def upgrade() -> None:
    op.create_table(
        "support_ai_agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_setting_id", sa.String(40), nullable=True),
        sa.Column(
            "sku_knowledge_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "file_knowledge_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "multilingual_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "min_retrieval_score",
            sa.Numeric(6, 5),
            nullable=False,
            server_default="0.12000",
        ),
        sa.Column(
            "min_answer_confidence",
            sa.Numeric(6, 5),
            nullable=False,
            server_default="0.65000",
        ),
        sa.Column("max_sources", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "daily_auto_reply_limit",
            sa.Integer(),
            nullable=False,
            server_default="500",
        ),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column(
            "handoff_messages",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(agent_code) = 8",
            name="ck_support_ai_agents_agent_code_length",
        ),
        sa.CheckConstraint(
            "min_retrieval_score >= 0 AND min_retrieval_score <= 1",
            name="ck_support_ai_agents_retrieval_score_range",
        ),
        sa.CheckConstraint(
            "min_answer_confidence >= 0 AND min_answer_confidence <= 1",
            name="ck_support_ai_agents_answer_confidence_range",
        ),
        sa.CheckConstraint(
            "max_sources >= 1 AND max_sources <= 12",
            name="ck_support_ai_agents_max_sources_range",
        ),
        sa.CheckConstraint(
            "daily_auto_reply_limit >= 1 AND daily_auto_reply_limit <= 100000",
            name="ck_support_ai_agents_daily_limit_range",
        ),
        sa.ForeignKeyConstraint(
            ["provider_setting_id"],
            ["support_ai_provider_settings.id"],
            name="fk_support_ai_agents_provider_setting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_support_ai_agents_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_support_ai_agents_updated_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_agents"),
        sa.UniqueConstraint(
            "agent_code",
            name="uq_support_ai_agents_agent_code",
        ),
    )
    op.create_index(
        "ix_support_ai_agents_enabled_updated",
        "support_ai_agents",
        ["enabled", "updated_at"],
    )

    with op.batch_alter_table("support_ai_settings") as batch:
        batch.add_column(sa.Column("agent_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_support_ai_settings_agent",
            "support_ai_agents",
            ["agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_support_ai_settings_agent_id", ["agent_id"])

    with op.batch_alter_table("support_ai_knowledge_sources") as batch:
        batch.add_column(sa.Column("agent_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_support_ai_knowledge_sources_agent",
            "support_ai_agents",
            ["agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_support_ai_knowledge_sources_agent_id", ["agent_id"])

    # Offline SQL generation has no result rows to iterate. Production upgrades
    # run online and execute the compatibility backfill below.
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    existing = bind.execute(
        sa.text(
            """
            SELECT settings.tenant_id, settings.enabled,
                   settings.provider_setting_id,
                   settings.sku_knowledge_enabled,
                   settings.file_knowledge_enabled,
                   settings.multilingual_enabled,
                   settings.min_retrieval_score,
                   settings.min_answer_confidence,
                   settings.max_sources,
                   settings.daily_auto_reply_limit,
                   settings.system_prompt,
                   settings.handoff_messages,
                   settings.updated_by_user_id,
                   tenants.name AS tenant_name
            FROM support_ai_settings AS settings
            JOIN tenants ON tenants.id = settings.tenant_id
            WHERE settings.deleted_at IS NULL AND tenants.deleted_at IS NULL
            """
        )
    ).mappings().all()
    agents = sa.table(
        "support_ai_agents",
        sa.column("id", sa.Uuid()),
        sa.column("agent_code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("provider_setting_id", sa.String()),
        sa.column("sku_knowledge_enabled", sa.Boolean()),
        sa.column("file_knowledge_enabled", sa.Boolean()),
        sa.column("multilingual_enabled", sa.Boolean()),
        sa.column("min_retrieval_score", sa.Numeric()),
        sa.column("min_answer_confidence", sa.Numeric()),
        sa.column("max_sources", sa.Integer()),
        sa.column("daily_auto_reply_limit", sa.Integer()),
        sa.column("system_prompt", sa.Text()),
        sa.column("handoff_messages", JSON_DOCUMENT),
        sa.column("created_by_user_id", sa.Uuid()),
        sa.column("updated_by_user_id", sa.Uuid()),
    )
    used_codes: set[str] = set()
    for row in existing:
        agent_id = _database_uuid()
        bind.execute(
            agents.insert(),
            {
                "id": agent_id,
                "agent_code": _agent_code(used_codes),
                "name": f"{row['tenant_name']} 智能客服"[:160],
                "description": None,
                "enabled": row["enabled"],
                "provider_setting_id": row["provider_setting_id"],
                "sku_knowledge_enabled": row["sku_knowledge_enabled"],
                "file_knowledge_enabled": row["file_knowledge_enabled"],
                "multilingual_enabled": row["multilingual_enabled"],
                "min_retrieval_score": row["min_retrieval_score"],
                "min_answer_confidence": row["min_answer_confidence"],
                "max_sources": row["max_sources"],
                "daily_auto_reply_limit": row["daily_auto_reply_limit"],
                "system_prompt": row["system_prompt"],
                "handoff_messages": row["handoff_messages"] or {},
                "created_by_user_id": row["updated_by_user_id"],
                "updated_by_user_id": row["updated_by_user_id"],
            },
        )
        bind.execute(
            sa.text(
                "UPDATE support_ai_settings SET agent_id = :agent_id "
                "WHERE tenant_id = :tenant_id"
            ),
            {"agent_id": _raw_uuid(agent_id), "tenant_id": row["tenant_id"]},
        )

    bind.execute(
        sa.text(
            "UPDATE support_ai_knowledge_sources "
            "SET agent_id = ("
            "SELECT settings.agent_id FROM support_ai_settings AS settings "
            "WHERE settings.tenant_id = support_ai_knowledge_sources.tenant_id"
            ") WHERE agent_id IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("support_ai_knowledge_sources") as batch:
        batch.drop_index("ix_support_ai_knowledge_sources_agent_id")
        batch.drop_constraint(
            "fk_support_ai_knowledge_sources_agent",
            type_="foreignkey",
        )
        batch.drop_column("agent_id")
    with op.batch_alter_table("support_ai_settings") as batch:
        batch.drop_index("ix_support_ai_settings_agent_id")
        batch.drop_constraint("fk_support_ai_settings_agent", type_="foreignkey")
        batch.drop_column("agent_id")
    op.drop_index(
        "ix_support_ai_agents_enabled_updated",
        table_name="support_ai_agents",
    )
    op.drop_table("support_ai_agents")
