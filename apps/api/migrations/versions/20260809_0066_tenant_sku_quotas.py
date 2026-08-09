"""Add configurable SKU quotas to merchant subscriptions.

Revision ID: 20260809_0066
Revises: 20260809_0065
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0066"
down_revision = "20260809_0065"
branch_labels = None
depends_on = None

SKU_LIMIT_CONSTRAINT = "sku_limit_nonnegative"


def upgrade() -> None:
    op.add_column(
        "tenant_subscriptions",
        sa.Column("sku_limit", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE tenant_subscriptions SET sku_limit = CASE "
            "WHEN subscription_tier = 'TRIAL' THEN 500 "
            "WHEN subscription_tier IN ('STANDARD', 'SILVER') THEN 5000 "
            "ELSE NULL END"
        )
    )
    with op.batch_alter_table("tenant_subscriptions") as batch:
        batch.create_check_constraint(
            SKU_LIMIT_CONSTRAINT,
            "sku_limit IS NULL OR sku_limit >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_subscriptions") as batch:
        batch.drop_constraint(SKU_LIMIT_CONSTRAINT, type_="check")
        batch.drop_column("sku_limit")
