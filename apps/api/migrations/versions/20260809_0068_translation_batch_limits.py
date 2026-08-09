"""Add platform-managed catalog translation batch limits.

Revision ID: 20260809_0068
Revises: 20260809_0067
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0068"
down_revision = "20260809_0067"
branch_labels = None
depends_on = None


BATCH_SIZE_CONSTRAINT = (
    "ck_translation_provider_settings_catalog_batch_size_supported"
)
BATCH_CHARACTERS_CONSTRAINT = (
    "ck_translation_provider_settings_catalog_batch_characters_supported"
)


def upgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "catalog_batch_size",
                sa.Integer(),
                nullable=False,
                server_default="50",
            )
        )
        batch.add_column(
            sa.Column(
                "catalog_batch_characters",
                sa.Integer(),
                nullable=False,
                server_default="10000",
            )
        )
        batch.create_check_constraint(
            BATCH_SIZE_CONSTRAINT,
            "catalog_batch_size >= 1 AND catalog_batch_size <= 200",
        )
        batch.create_check_constraint(
            BATCH_CHARACTERS_CONSTRAINT,
            "catalog_batch_characters >= 1000 "
            "AND catalog_batch_characters <= 100000",
        )


def downgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(BATCH_CHARACTERS_CONSTRAINT, type_="check")
        batch.drop_constraint(BATCH_SIZE_CONSTRAINT, type_="check")
        batch.drop_column("catalog_batch_characters")
        batch.drop_column("catalog_batch_size")
