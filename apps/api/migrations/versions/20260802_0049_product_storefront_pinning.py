"""Add product storefront pinning.

Revision ID: 20260802_0049
Revises: 20260802_0048
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0049"
down_revision = "20260802_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.add_column(
            sa.Column("storefront_pinned_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index(
            "ix_products_tenant_category_pinned",
            ["tenant_id", "category_id", "storefront_pinned_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_index("ix_products_tenant_category_pinned")
        batch.drop_column("storefront_pinned_at")
