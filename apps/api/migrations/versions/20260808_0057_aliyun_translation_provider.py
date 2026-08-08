"""Add Aliyun Machine Translation provider credentials.

Revision ID: 20260808_0057
Revises: 20260808_0056
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260808_0057"
down_revision = "20260808_0056"
branch_labels = None
depends_on = None


PROVIDER_CONSTRAINT = "ck_translation_provider_settings_provider_supported"
ACTIVE_KEY_CONSTRAINT = "ck_translation_provider_settings_active_key_required"


def upgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.add_column(sa.Column("region_id", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column("access_key_id_ciphertext", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("access_key_id_last_four", sa.String(4), nullable=True)
        )
        batch.drop_constraint(PROVIDER_CONSTRAINT, type_="check")
        batch.drop_constraint(ACTIVE_KEY_CONSTRAINT, type_="check")
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


def downgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(ACTIVE_KEY_CONSTRAINT, type_="check")
        batch.drop_constraint(PROVIDER_CONSTRAINT, type_="check")
        batch.create_check_constraint(
            PROVIDER_CONSTRAINT,
            "provider = 'openai-compatible'",
        )
        batch.create_check_constraint(
            ACTIVE_KEY_CONSTRAINT,
            "is_active = false OR api_key_ciphertext IS NOT NULL",
        )
        batch.drop_column("access_key_id_last_four")
        batch.drop_column("access_key_id_ciphertext")
        batch.drop_column("region_id")
