"""Add versioned, human-reviewed support AI training packages.

Revision ID: 20260813_0083
Revises: 20260813_0082
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260813_0083"
down_revision = "20260813_0082"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _audit_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "support_ai_training_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("source_tenant_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column(
            "language", sa.String(35), nullable=False, server_default="zh-CN"
        ),
        sa.Column("customer_message", sa.Text(), nullable=False),
        sa.Column("ideal_response", sa.Text(), nullable=False),
        sa.Column(
            "response_action", sa.String(24), nullable=False, server_default="ANSWER"
        ),
        sa.Column(
            "grounding_mode", sa.String(40), nullable=False, server_default="EVIDENCE"
        ),
        sa.Column("behavior_notes", sa.Text(), nullable=True),
        sa.Column(
            "required_evidence_types",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "tags", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "forbidden_patterns",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "source_type", sa.String(40), nullable=False, server_default="MANUAL"
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "response_action IN ('ANSWER', 'CLARIFY', 'HANDOFF')",
            name="ck_support_ai_training_cases_response_action_allowed",
        ),
        sa.CheckConstraint(
            "grounding_mode IN ('EVIDENCE', 'GENERAL_GUIDANCE', 'APPROVED_COMPANY_PROFILE')",
            name="ck_support_ai_training_cases_grounding_mode_allowed",
        ),
        sa.CheckConstraint(
            "source_type IN ('MANUAL', 'PRODUCT_GENERATED', 'CONVERSATION_CORRECTION', 'IMPORT')",
            name="ck_support_ai_training_cases_source_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'ARCHIVED')",
            name="ck_support_ai_training_cases_status_allowed",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_support_ai_training_cases_sort_order_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["support_ai_agents.id"],
            name="fk_support_ai_training_cases_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_training_cases_source_tenant",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_support_ai_training_cases_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_support_ai_training_cases_updated_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_training_cases"),
        sa.UniqueConstraint(
            "agent_id",
            "external_id",
            name="uq_support_ai_training_cases_external",
        ),
    )
    op.create_index(
        "ix_support_ai_training_cases_agent_status",
        "support_ai_training_cases",
        ["agent_id", "status", "updated_at"],
    )

    op.create_table(
        "support_ai_training_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column(
            "scopes", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "source_case_ids",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'ARCHIVED')",
            name="ck_support_ai_training_rules_status_allowed",
        ),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 1000",
            name="ck_support_ai_training_rules_priority_range",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["support_ai_agents.id"],
            name="fk_support_ai_training_rules_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_support_ai_training_rules_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_support_ai_training_rules_updated_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_training_rules"),
        sa.UniqueConstraint(
            "agent_id", "rule_key", name="uq_support_ai_training_rules_key"
        ),
    )
    op.create_index(
        "ix_support_ai_training_rules_agent_status",
        "support_ai_training_rules",
        ["agent_id", "status", "priority"],
    )

    op.create_table(
        "support_ai_training_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="PUBLISHED"
        ),
        sa.Column("package_hash", sa.String(64), nullable=False),
        sa.Column("compiled_prompt", sa.Text(), nullable=False),
        sa.Column(
            "case_snapshot",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "rule_snapshot",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_support_ai_training_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PUBLISHED', 'RETIRED')",
            name="ck_support_ai_training_versions_status_allowed",
        ),
        sa.CheckConstraint(
            "length(package_hash) = 64",
            name="ck_support_ai_training_versions_package_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["support_ai_agents.id"],
            name="fk_support_ai_training_versions_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            name="fk_support_ai_training_versions_published_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_training_versions"),
        sa.UniqueConstraint(
            "agent_id",
            "version_number",
            name="uq_support_ai_training_versions_number",
        ),
    )
    op.create_index(
        "ix_support_ai_training_versions_agent_status",
        "support_ai_training_versions",
        ["agent_id", "status", "version_number"],
    )
    op.create_index(
        "uq_support_ai_training_versions_active_agent",
        "support_ai_training_versions",
        ["agent_id"],
        unique=True,
        sqlite_where=sa.text("status = 'PUBLISHED'"),
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    with op.batch_alter_table("support_ai_settings") as batch:
        batch.add_column(sa.Column("training_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("training_prompt", sa.Text(), nullable=True))
        batch.add_column(sa.Column("training_package_hash", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column(
                "training_examples",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.create_foreign_key(
            "fk_support_ai_settings_training_version",
            "support_ai_training_versions",
            ["training_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("support_ai_runs") as batch:
        batch.add_column(sa.Column("training_version_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column(
                "training_case_ids",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.create_foreign_key(
            "fk_support_ai_runs_training_version",
            "support_ai_training_versions",
            ["training_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("support_ai_runs") as batch:
        batch.drop_constraint(
            "fk_support_ai_runs_training_version", type_="foreignkey"
        )
        batch.drop_column("training_case_ids")
        batch.drop_column("training_version_id")
    with op.batch_alter_table("support_ai_settings") as batch:
        batch.drop_constraint(
            "fk_support_ai_settings_training_version", type_="foreignkey"
        )
        batch.drop_column("training_examples")
        batch.drop_column("training_package_hash")
        batch.drop_column("training_prompt")
        batch.drop_column("training_version_id")
    op.drop_index(
        "uq_support_ai_training_versions_active_agent",
        table_name="support_ai_training_versions",
    )
    op.drop_index(
        "ix_support_ai_training_versions_agent_status",
        table_name="support_ai_training_versions",
    )
    op.drop_table("support_ai_training_versions")
    op.drop_index(
        "ix_support_ai_training_rules_agent_status",
        table_name="support_ai_training_rules",
    )
    op.drop_table("support_ai_training_rules")
    op.drop_index(
        "ix_support_ai_training_cases_agent_status",
        table_name="support_ai_training_cases",
    )
    op.drop_table("support_ai_training_cases")
