"""Add a tenant-scoped checksum index for product images.

Revision ID: 20260809_0059
Revises: 20260809_0058
"""

from __future__ import annotations

from alembic import op


revision = "20260809_0059"
down_revision = "20260809_0058"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_product_images_tenant_sha256"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "product_images",
        ["tenant_id", "sha256"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="product_images")
