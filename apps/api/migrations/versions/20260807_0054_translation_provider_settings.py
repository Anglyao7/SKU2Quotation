"""Add platform-managed translation provider settings.

Revision ID: 20260807_0054
Revises: 20260806_0053
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260807_0054"
down_revision = "20260806_0053"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "translation_provider_settings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column(
            "provider",
            sa.String(40),
            nullable=False,
            server_default="openai-compatible",
        ),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column(
            "max_tokens",
            sa.Integer(),
            nullable=False,
            server_default="16384",
        ),
        sa.Column(
            "reasoning_effort",
            sa.String(20),
            nullable=False,
            server_default="low",
        ),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("api_key_last_four", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", U(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider = 'openai-compatible'",
            name="ck_translation_provider_settings_provider_supported",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="ck_translation_provider_settings_timeout_supported",
        ),
        sa.CheckConstraint(
            "max_tokens >= 512 AND max_tokens <= 32768",
            name="ck_translation_provider_settings_max_tokens_supported",
        ),
        sa.CheckConstraint(
            "reasoning_effort IN ('none', 'minimal', 'low', 'medium', 'high')",
            name="ck_translation_provider_settings_reasoning_effort_supported",
        ),
        sa.CheckConstraint(
            "is_active = false OR api_key_ciphertext IS NOT NULL",
            name="ck_translation_provider_settings_active_key_required",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_translation_provider_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=(
                "fk_translation_provider_settings_updated_by_user_id_users"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_translation_provider_settings",
        ),
    )


def downgrade() -> None:
    op.drop_table("translation_provider_settings")
