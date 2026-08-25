"""Release deleted catalog identities and relationships.

Revision ID: 20260825_0110
Revises: 20260825_0109
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260825_0110"
down_revision = "20260825_0109"
branch_labels = None
depends_on = None


def _active_predicate(column: str | None = None) -> sa.TextClause:
    if column is None:
        return sa.text("deleted_at IS NULL")
    return sa.text(f"deleted_at IS NULL AND {column} IS NOT NULL")


def _live_sku_predicate(column: str | None = None) -> sa.TextClause:
    suffix = f" AND {column} IS NOT NULL" if column else ""
    return sa.text(f"deleted_at IS NULL AND status <> 'ARCHIVED'{suffix}")


def upgrade() -> None:
    # The original schema used full-table unique constraints.  Deletion is a
    # soft archive for audit/history, so those historical rows must not reserve
    # a code or source identity for the next catalog import.
    with op.batch_alter_table("products") as batch:
        batch.drop_constraint("uq_products_tenant_code", type_="unique")
    op.create_index(
        "uq_products_tenant_code_active",
        "products",
        ["tenant_id", "product_code"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status <> 'ARCHIVED' AND product_code IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "deleted_at IS NULL AND status <> 'ARCHIVED' AND product_code IS NOT NULL"
        ),
    )

    with op.batch_alter_table("skus") as batch:
        batch.drop_constraint("uq_skus_tenant_code", type_="unique")
    op.execute(
        sa.text(
            "UPDATE products "
            "SET category_id = NULL, storefront_pinned_at = NULL "
            "WHERE deleted_at IS NOT NULL OR status = 'ARCHIVED'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE skus "
            "SET supplier_id = NULL, source_sku_code = NULL "
            "WHERE deleted_at IS NOT NULL OR status = 'ARCHIVED'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE supplier_products "
            "SET status = 'INACTIVE', "
            "deleted_at = COALESCE(deleted_at, updated_at, CURRENT_TIMESTAMP), "
            "version = version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE product_id IN (SELECT id FROM products WHERE deleted_at IS NOT NULL OR status = 'ARCHIVED') "
            "OR sku_id IN (SELECT id FROM skus WHERE deleted_at IS NOT NULL OR status = 'ARCHIVED')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE product_categories "
            "SET cover_source = 'NONE', cover_product_id = NULL, cover_object_key = NULL, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE cover_source = 'PRODUCT' "
            "AND cover_product_id IN (SELECT id FROM products WHERE deleted_at IS NOT NULL OR status = 'ARCHIVED')"
        )
    )
    op.drop_index("uq_skus_tenant_source_code", table_name="skus")
    op.create_index(
        "uq_skus_tenant_code_active",
        "skus",
        ["tenant_id", "sku_code"],
        unique=True,
        postgresql_where=_live_sku_predicate(),
        sqlite_where=_live_sku_predicate(),
    )
    op.create_index(
        "uq_skus_tenant_source_code",
        "skus",
        ["tenant_id", "source_sku_code"],
        unique=True,
        postgresql_where=_live_sku_predicate("source_sku_code"),
        sqlite_where=_live_sku_predicate("source_sku_code"),
    )
    op.drop_index("uq_skus_tenant_product_sequence", table_name="skus")
    op.create_index(
        "uq_skus_tenant_product_sequence",
        "skus",
        ["tenant_id", "product_id", "sku_sequence"],
        unique=True,
        postgresql_where=_live_sku_predicate("sku_sequence"),
        sqlite_where=_live_sku_predicate("sku_sequence"),
    )

    with op.batch_alter_table("supplier_products") as batch:
        batch.drop_constraint("uq_supplier_products_tenant_source_sku", type_="unique")
    op.create_index(
        "uq_supplier_products_tenant_source_sku_active",
        "supplier_products",
        ["tenant_id", "supplier_id", "product_id", "supplier_sku"],
        unique=True,
        postgresql_where=_active_predicate(),
        sqlite_where=_active_predicate(),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_supplier_products_tenant_source_sku_active",
        table_name="supplier_products",
    )
    with op.batch_alter_table("supplier_products") as batch:
        batch.create_unique_constraint(
            "uq_supplier_products_tenant_source_sku",
            ["tenant_id", "supplier_id", "product_id", "supplier_sku"],
        )

    op.drop_index("uq_skus_tenant_product_sequence", table_name="skus")
    op.create_index(
        "uq_skus_tenant_product_sequence",
        "skus",
        ["tenant_id", "product_id", "sku_sequence"],
        unique=True,
    )
    op.drop_index("uq_skus_tenant_source_code", table_name="skus")
    op.create_index(
        "uq_skus_tenant_source_code",
        "skus",
        ["tenant_id", "source_sku_code"],
        unique=True,
    )
    op.drop_index("uq_skus_tenant_code_active", table_name="skus")
    with op.batch_alter_table("skus") as batch:
        batch.create_unique_constraint(
            "uq_skus_tenant_code",
            ["tenant_id", "sku_code"],
        )

    op.drop_index("uq_products_tenant_code_active", table_name="products")
    with op.batch_alter_table("products") as batch:
        batch.create_unique_constraint(
            "uq_products_tenant_code",
            ["tenant_id", "product_code"],
        )
