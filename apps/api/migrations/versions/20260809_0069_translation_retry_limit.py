"""Add platform-managed catalog translation retry limit.

Revision ID: 20260809_0069
Revises: 20260809_0068
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0069"
down_revision = "20260809_0068"
branch_labels = None
depends_on = None


RETRY_COUNT_CONSTRAINT = (
    "ck_translation_provider_settings_max_retry_count_supported"
)


def upgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "max_retry_count",
                sa.Integer(),
                nullable=False,
                server_default="3",
            )
        )
        batch.create_check_constraint(
            RETRY_COUNT_CONSTRAINT,
            "max_retry_count >= 0 AND max_retry_count <= 10",
        )


def downgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(RETRY_COUNT_CONSTRAINT, type_="check")
        batch.drop_column("max_retry_count")
