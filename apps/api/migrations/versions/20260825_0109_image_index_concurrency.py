"""Add administrator-managed image index concurrency.

Revision ID: 20260825_0109
Revises: 20260824_0108
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260825_0109"
down_revision = "20260824_0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("image_embedding_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "index_concurrency",
                sa.Integer(),
                nullable=False,
                server_default="16",
            )
        )
        batch.create_check_constraint(
            "ck_image_embedding_provider_settings_index_concurrency_supported",
            "index_concurrency >= 1 AND index_concurrency <= 32",
        )


def downgrade() -> None:
    with op.batch_alter_table("image_embedding_provider_settings") as batch:
        batch.drop_constraint(
            "ck_image_embedding_provider_settings_index_concurrency_supported",
            type_="check",
        )
        batch.drop_column("index_concurrency")
