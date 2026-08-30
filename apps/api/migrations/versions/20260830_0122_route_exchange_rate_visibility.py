"""Configure exchange-rate visibility per storefront route.

Revision ID: 20260830_0122
Revises: 20260830_0121
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260830_0122"
down_revision = "20260830_0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "storefront_exchange_rates_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("storefront_custom_pages") as batch:
        batch.add_column(
            sa.Column(
                "exchange_rates_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("storefront_custom_pages") as batch:
        batch.drop_column("exchange_rates_enabled")
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("storefront_exchange_rates_enabled")
