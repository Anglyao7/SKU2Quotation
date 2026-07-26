"""Link each SKU to an optional inventory supplier.

Revision ID: 20260726_0036
Revises: 20260726_0035
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260726_0036"
down_revision = "20260726_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # Rebuilding ``skus`` would require dropping a table referenced by
        # inventory, catalog, quote, price and supplier-source tables. Keep the
        # local/demo SQLite path non-destructive; production PostgreSQL receives
        # the tenant-scoped composite foreign key below.
        op.add_column(
            "skus",
            sa.Column("supplier_id", sa.String(40), nullable=True),
        )
        op.create_index(
            "ix_skus_tenant_supplier",
            "skus",
            ["tenant_id", "supplier_id"],
        )
        return
    with op.batch_alter_table("skus") as batch:
        batch.add_column(sa.Column("supplier_id", sa.String(40), nullable=True))
        batch.create_foreign_key(
            "fk_skus_tenant_supplier",
            "suppliers",
            ["tenant_id", "supplier_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_skus_tenant_supplier",
            ["tenant_id", "supplier_id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index("ix_skus_tenant_supplier", table_name="skus")
        op.drop_column("skus", "supplier_id")
        return
    with op.batch_alter_table("skus") as batch:
        batch.drop_index("ix_skus_tenant_supplier")
        batch.drop_constraint("fk_skus_tenant_supplier", type_="foreignkey")
        batch.drop_column("supplier_id")
