"""Add merchant hot-product merchandising preference.

Revision ID: 20260802_0050
Revises: 20260802_0049
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0050"
down_revision = "20260802_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "hot_products_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("hot_products_enabled")
