"""Allow managed support AI profiles to use Qwen's OpenAI-compatible API.

Revision ID: 20260824_0108
Revises: 20260824_0107
"""

from __future__ import annotations

from alembic import op


revision = "20260824_0108"
down_revision = "20260824_0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("support_ai_provider_settings") as batch:
        batch.drop_constraint(
            "ck_support_ai_provider_settings_provider_supported",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_support_ai_provider_settings_provider_supported",
            "provider IN ('openai-compatible', 'qwen')",
        )


def downgrade() -> None:
    with op.batch_alter_table("support_ai_provider_settings") as batch:
        batch.drop_constraint(
            "ck_support_ai_provider_settings_provider_supported",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_support_ai_provider_settings_provider_supported",
            "provider = 'openai-compatible'",
        )
