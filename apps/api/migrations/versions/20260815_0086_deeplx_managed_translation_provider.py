"""Allow DeepLX in platform-managed translation settings.

Revision ID: 20260815_0086
Revises: 20260814_0085
"""

from __future__ import annotations

from alembic import op


revision = "20260815_0086"
down_revision = "20260814_0085"
branch_labels = None
depends_on = None


PROVIDER_CONSTRAINT = "ck_translation_provider_settings_provider_supported"
ACTIVE_KEY_CONSTRAINT = "ck_translation_provider_settings_active_key_required"


def upgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(PROVIDER_CONSTRAINT, type_="check")
        batch.drop_constraint(ACTIVE_KEY_CONSTRAINT, type_="check")
        batch.create_check_constraint(
            PROVIDER_CONSTRAINT,
            "provider IN ('openai-compatible', 'deeplx', 'aliyun-alimt')",
        )
        batch.create_check_constraint(
            ACTIVE_KEY_CONSTRAINT,
            "is_active = false OR ("
            "api_key_ciphertext IS NOT NULL AND ("
            "provider IN ('openai-compatible', 'deeplx') OR "
            "access_key_id_ciphertext IS NOT NULL))",
        )


def downgrade() -> None:
    op.execute(
        "UPDATE translation_provider_settings "
        "SET provider = 'openai-compatible', is_active = false "
        "WHERE provider = 'deeplx'"
    )
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(ACTIVE_KEY_CONSTRAINT, type_="check")
        batch.drop_constraint(PROVIDER_CONSTRAINT, type_="check")
        batch.create_check_constraint(
            PROVIDER_CONSTRAINT,
            "provider IN ('openai-compatible', 'aliyun-alimt')",
        )
        batch.create_check_constraint(
            ACTIVE_KEY_CONSTRAINT,
            "is_active = false OR ("
            "api_key_ciphertext IS NOT NULL AND ("
            "provider = 'openai-compatible' OR "
            "access_key_id_ciphertext IS NOT NULL))",
        )
