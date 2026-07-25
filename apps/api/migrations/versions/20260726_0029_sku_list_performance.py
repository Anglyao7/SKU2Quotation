"""Add the tenant-scoped SKU listing index.

Revision ID: 20260726_0029
Revises: 20260725_0028
"""

from __future__ import annotations

from alembic import op


revision = "20260726_0029"
down_revision = "20260725_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_skus_tenant_status_updated",
        "skus",
        ["tenant_id", "status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_skus_tenant_status_updated", table_name="skus")
