"""Add tenant-scoped warehouses and perpetual inventory management.

Revision ID: 20260726_0030
Revises: 20260726_0029
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op


revision = "20260726_0030"
down_revision = "20260726_0029"
branch_labels = None
depends_on = None


NOW = sa.text("CURRENT_TIMESTAMP")
ZERO = sa.text("0")
ONE = sa.text("1")
U = lambda: sa.Uuid(as_uuid=True)

INVENTORY_TABLES = (
    "warehouses",
    "inventory_balances",
    "purchase_orders",
    "purchase_order_items",
    "sales_orders",
    "sales_order_items",
    "inventory_documents",
    "inventory_document_items",
    "inventory_movements",
)

PERMISSION_DEFINITIONS = (
    (
        "inventory.view",
        "inventory",
        "view",
        "View inventory and stock movements",
    ),
    (
        "inventory.adjust",
        "inventory",
        "adjust",
        "Post inventory adjustments",
    ),
    (
        "inventory.purchase",
        "inventory",
        "purchase",
        "Manage purchase orders and receipts",
    ),
    (
        "inventory.sale",
        "inventory",
        "sale",
        "Manage sales orders and shipments",
    ),
    (
        "inventory.transfer",
        "inventory",
        "transfer",
        "Transfer stock between warehouses",
    ),
    (
        "inventory.warehouse_manage",
        "inventory",
        "warehouse_manage",
        "Manage warehouses",
    ),
)

ROLE_PERMISSION_CODES = {
    "OWNER": {item[0] for item in PERMISSION_DEFINITIONS},
    "ADMIN": {item[0] for item in PERMISSION_DEFINITIONS},
    "SALES": {"inventory.view", "inventory.sale"},
    "PURCHASING": {
        "inventory.view",
        "inventory.adjust",
        "inventory.purchase",
        "inventory.transfer",
    },
    "VIEWER": {"inventory.view"},
}


def _audit() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _tenant_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=name,
        ondelete="CASCADE",
    )


def _create_tables() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=ONE),
        sa.Column("created_by_membership_id", U(), nullable=True),
        *_audit(),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')", name="status_allowed"
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        _tenant_fk("fk_warehouses_tenant_id_tenants"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_warehouses_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_warehouses_tenant_code"
        ),
    )
    op.create_index(
        "ix_warehouses_tenant_status",
        "warehouses",
        ["tenant_id", "status"],
    )
    op.create_index(
        "uq_warehouses_tenant_default",
        "warehouses",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_default = 1 AND deleted_at IS NULL"),
    )

    op.create_table(
        "inventory_balances",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("warehouse_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column(
            "on_hand_quantity",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column(
            "reserved_quantity",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column(
            "average_cost",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column(
            "reorder_point",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=ONE),
        *_audit(),
        sa.CheckConstraint("on_hand_quantity >= 0", name="on_hand_nonnegative"),
        sa.CheckConstraint("reserved_quantity >= 0", name="reserved_nonnegative"),
        sa.CheckConstraint(
            "reserved_quantity <= on_hand_quantity",
            name="reserved_not_above_on_hand",
        ),
        sa.CheckConstraint("average_cost >= 0", name="average_cost_nonnegative"),
        sa.CheckConstraint("reorder_point >= 0", name="reorder_point_nonnegative"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        _tenant_fk("fk_inventory_balances_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_balances_tenant_warehouse",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_inventory_balances_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "warehouse_id",
            "sku_id",
            name="uq_inventory_balance_location_sku",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_balances_tenant_identity"
        ),
    )
    op.create_index(
        "ix_inventory_balances_tenant_warehouse_stock",
        "inventory_balances",
        ["tenant_id", "warehouse_id", "on_hand_quantity"],
    )
    op.create_index(
        "ix_inventory_balances_tenant_sku",
        "inventory_balances",
        ["tenant_id", "sku_id"],
    )

    op.create_table(
        "purchase_orders",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("order_number", sa.String(80), nullable=False),
        sa.Column("supplier_name", sa.String(300), nullable=False),
        sa.Column("warehouse_id", U(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "total_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=ONE),
        sa.Column("created_by_membership_id", U(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit(),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'PARTIALLY_RECEIVED', "
            "'RECEIVED', 'CANCELLED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        _tenant_fk("fk_purchase_orders_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_purchase_orders_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_purchase_orders_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_purchase_orders_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "order_number",
            name="uq_purchase_orders_tenant_number",
        ),
    )
    op.create_index(
        "ix_purchase_orders_tenant_status_updated",
        "purchase_orders",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "purchase_order_items",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("purchase_order_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "received_quantity",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column("unit_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total", sa.Numeric(20, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.CheckConstraint("line_number >= 1", name="line_number_positive"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("received_quantity >= 0", name="received_nonnegative"),
        sa.CheckConstraint(
            "received_quantity <= quantity",
            name="received_not_above_ordered",
        ),
        sa.CheckConstraint(
            "unit_cost >= 0 AND line_total >= 0",
            name="amounts_nonnegative",
        ),
        _tenant_fk("fk_purchase_order_items_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "purchase_order_id"],
            ["purchase_orders.tenant_id", "purchase_orders.id"],
            name="fk_purchase_order_items_tenant_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_purchase_order_items_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_purchase_order_items_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "purchase_order_id",
            "line_number",
            name="uq_purchase_order_items_line",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "purchase_order_id",
            "sku_id",
            name="uq_purchase_order_items_sku",
        ),
    )

    op.create_table(
        "sales_orders",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("order_number", sa.String(80), nullable=False),
        sa.Column("customer_id", U(), nullable=True),
        sa.Column("customer_name", sa.String(300), nullable=False),
        sa.Column("warehouse_id", U(), nullable=False),
        sa.Column("source_quotation_id", U(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "total_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=ONE),
        sa.Column("created_by_membership_id", U(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit(),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'PARTIALLY_SHIPPED', "
            "'SHIPPED', 'CANCELLED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        _tenant_fk("fk_sales_orders_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_sales_orders_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_sales_orders_tenant_customer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_quotation_id"],
            ["quotations.tenant_id", "quotations.id"],
            name="fk_sales_orders_tenant_quotation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_sales_orders_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_sales_orders_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "order_number",
            name="uq_sales_orders_tenant_number",
        ),
    )
    op.create_index(
        "ix_sales_orders_tenant_status_updated",
        "sales_orders",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "sales_order_items",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("sales_order_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "reserved_quantity",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column(
            "shipped_quantity",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("line_total", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "cost_amount",
            sa.Numeric(20, 6),
            nullable=False,
            server_default=ZERO,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit(),
        sa.CheckConstraint("line_number >= 1", name="line_number_positive"),
        sa.CheckConstraint("quantity > 0", name="quantity_positive"),
        sa.CheckConstraint("reserved_quantity >= 0", name="reserved_nonnegative"),
        sa.CheckConstraint("shipped_quantity >= 0", name="shipped_nonnegative"),
        sa.CheckConstraint(
            "reserved_quantity + shipped_quantity <= quantity",
            name="fulfilled_not_above_ordered",
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND line_total >= 0",
            name="amounts_nonnegative",
        ),
        _tenant_fk("fk_sales_order_items_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sales_order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            name="fk_sales_order_items_tenant_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_sales_order_items_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_sales_order_items_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sales_order_id",
            "line_number",
            name="uq_sales_order_items_line",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sales_order_id",
            "sku_id",
            name="uq_sales_order_items_sku",
        ),
    )

    op.create_table(
        "inventory_documents",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("document_number", sa.String(80), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'POSTED'"),
        ),
        sa.Column("warehouse_id", U(), nullable=False),
        sa.Column("counterparty_warehouse_id", U(), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=True),
        sa.Column("source_id", U(), nullable=True),
        sa.Column("source_number", sa.String(100), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("created_by_membership_id", U(), nullable=False),
        *_audit(),
        sa.CheckConstraint(
            "document_type IN ('PURCHASE_RECEIPT', 'SALES_RESERVATION', "
            "'SALES_SHIPMENT', 'SALES_RELEASE', 'MANUAL_ADJUSTMENT', "
            "'STOCK_TRANSFER')",
            name="document_type_allowed",
        ),
        sa.CheckConstraint("status = 'POSTED'", name="posted_only"),
        _tenant_fk("fk_inventory_documents_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_documents_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "counterparty_warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_documents_tenant_counterparty_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_inventory_documents_tenant_creator",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_documents_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_number",
            name="uq_inventory_documents_tenant_number",
        ),
    )
    op.create_index(
        "ix_inventory_documents_tenant_type_occurred",
        "inventory_documents",
        ["tenant_id", "document_type", "occurred_at"],
    )
    op.create_index(
        "uq_inventory_documents_tenant_idempotency",
        "inventory_documents",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(
            "idempotency_key IS NOT NULL AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_table(
        "inventory_document_items",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("document_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("purchase_order_item_id", U(), nullable=True),
        sa.Column("sales_order_item_id", U(), nullable=True),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(20, 6), nullable=True),
        *_audit(),
        sa.CheckConstraint("line_number >= 1", name="line_number_positive"),
        sa.CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name="unit_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "NOT (purchase_order_item_id IS NOT NULL "
            "AND sales_order_item_id IS NOT NULL)",
            name="single_source_item",
        ),
        _tenant_fk("fk_inventory_document_items_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["inventory_documents.tenant_id", "inventory_documents.id"],
            name="fk_inventory_document_items_tenant_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_inventory_document_items_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "purchase_order_item_id"],
            ["purchase_order_items.tenant_id", "purchase_order_items.id"],
            name="fk_inventory_document_items_tenant_purchase_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sales_order_item_id"],
            ["sales_order_items.tenant_id", "sales_order_items.id"],
            name="fk_inventory_document_items_tenant_sales_item",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_inventory_document_items_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "line_number",
            name="uq_inventory_document_items_line",
        ),
    )

    op.create_table(
        "inventory_movements",
        sa.Column("id", U(), primary_key=True),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("document_id", U(), nullable=False),
        sa.Column("document_item_id", U(), nullable=False),
        sa.Column("warehouse_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("movement_type", sa.String(40), nullable=False),
        sa.Column("on_hand_delta", sa.Numeric(20, 6), nullable=False),
        sa.Column("reserved_delta", sa.Numeric(20, 6), nullable=False),
        sa.Column("on_hand_before", sa.Numeric(20, 6), nullable=False),
        sa.Column("on_hand_after", sa.Numeric(20, 6), nullable=False),
        sa.Column("reserved_before", sa.Numeric(20, 6), nullable=False),
        sa.Column("reserved_after", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("average_cost_after", sa.Numeric(20, 6), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("created_by_membership_id", U(), nullable=False),
        *_audit(),
        sa.CheckConstraint(
            "movement_type IN ('PURCHASE_RECEIPT', 'SALES_RESERVATION', "
            "'SALES_SHIPMENT', 'SALES_RELEASE', 'MANUAL_ADJUSTMENT', "
            "'TRANSFER_OUT', 'TRANSFER_IN')",
            name="movement_type_allowed",
        ),
        sa.CheckConstraint(
            "on_hand_delta <> 0 OR reserved_delta <> 0",
            name="movement_delta_nonzero",
        ),
        sa.CheckConstraint(
            "on_hand_before >= 0 AND on_hand_after >= 0",
            name="on_hand_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_before >= 0 AND reserved_after >= 0",
            name="reserved_nonnegative",
        ),
        sa.CheckConstraint(
            "average_cost_after >= 0", name="average_cost_nonnegative"
        ),
        _tenant_fk("fk_inventory_movements_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["inventory_documents.tenant_id", "inventory_documents.id"],
            name="fk_inventory_movements_tenant_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_item_id"],
            ["inventory_document_items.tenant_id", "inventory_document_items.id"],
            name="fk_inventory_movements_tenant_document_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_movements_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_inventory_movements_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_movements_tenant_identity"
        ),
    )
    op.create_index(
        "ix_inventory_movements_tenant_location_sku_time",
        "inventory_movements",
        ["tenant_id", "warehouse_id", "sku_id", "occurred_at"],
    )
    op.create_index(
        "ix_inventory_movements_tenant_document",
        "inventory_movements",
        ["tenant_id", "document_id"],
    )


def _backfill_defaults_and_permissions() -> None:
    connection = op.get_bind()
    is_postgresql = connection.dialect.name == "postgresql"
    if is_postgresql:
        for table in ("tenants", "roles", "role_permissions"):
            op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')

    tenants = sa.table(
        "tenants",
        sa.column("id", U()),
        sa.column("default_currency", sa.String()),
        sa.column("status", sa.String()),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    warehouses = sa.table(
        "warehouses",
        sa.column("id", U()),
        sa.column("tenant_id", U()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("currency", sa.String()),
        sa.column("status", sa.String()),
        sa.column("is_default", sa.Boolean()),
        sa.column("version", sa.BigInteger()),
        sa.column("created_by_membership_id", U()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", U()),
        sa.column("code", sa.String()),
        sa.column("module", sa.String()),
        sa.column("action", sa.String()),
        sa.column("description", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table(
        "roles",
        sa.column("id", U()),
        sa.column("tenant_id", U()),
        sa.column("code", sa.String()),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", U()),
        sa.column("tenant_id", U()),
        sa.column("role_id", U()),
        sa.column("permission_id", U()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )

    now = datetime.now(UTC)
    tenant_rows = connection.execute(
        sa.select(tenants.c.id, tenants.c.default_currency).where(
            tenants.c.status == "active",
            tenants.c.deleted_at.is_(None),
        )
    ).all()
    for tenant_id, currency in tenant_rows:
        connection.execute(
            warehouses.insert().values(
                id=uuid4(),
                tenant_id=tenant_id,
                code="MAIN",
                name="默认仓库",
                currency=(currency or "CNY").upper(),
                status="ACTIVE",
                is_default=True,
                version=1,
                created_by_membership_id=None,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
        )

    permission_ids: dict[str, object] = {}
    for code, module, action, description in PERMISSION_DEFINITIONS:
        row = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.code == code)
        ).first()
        if row is None:
            permission_id = uuid4()
            connection.execute(
                permissions.insert().values(
                    id=permission_id,
                    code=code,
                    module=module,
                    action=action,
                    description=description,
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        else:
            permission_id = row.id
            connection.execute(
                permissions.update()
                .where(permissions.c.id == permission_id)
                .values(
                    module=module,
                    action=action,
                    description=description,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        permission_ids[code] = permission_id

    role_rows = connection.execute(
        sa.select(roles.c.id, roles.c.tenant_id, roles.c.code).where(
            roles.c.code.in_(tuple(ROLE_PERMISSION_CODES)),
            roles.c.deleted_at.is_(None),
        )
    ).all()
    for role_id, tenant_id, role_code in role_rows:
        for permission_code in ROLE_PERMISSION_CODES[str(role_code)]:
            permission_id = permission_ids[permission_code]
            assignment = connection.execute(
                sa.select(
                    role_permissions.c.id,
                    role_permissions.c.deleted_at,
                ).where(
                    role_permissions.c.tenant_id == tenant_id,
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if assignment is None:
                connection.execute(
                    role_permissions.insert().values(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        role_id=role_id,
                        permission_id=permission_id,
                        created_at=now,
                        updated_at=now,
                        deleted_at=None,
                    )
                )
            elif assignment.deleted_at is not None:
                connection.execute(
                    role_permissions.update()
                    .where(role_permissions.c.id == assignment.id)
                    .values(updated_at=now, deleted_at=None)
                )

    if is_postgresql:
        for table in ("role_permissions", "roles", "tenants"):
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in INVENTORY_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"FOR ALL USING (tenant_id = {tenant}) "
            f"WITH CHECK (tenant_id = {tenant})"
        )


def upgrade() -> None:
    _create_tables()
    if not context.is_offline_mode():
        _backfill_defaults_and_permissions()
    _enable_rls()


def downgrade() -> None:
    if not context.is_offline_mode():
        connection = op.get_bind()
        permissions = sa.table(
            "permissions",
            sa.column("id", U()),
            sa.column("code", sa.String()),
        )
        role_permissions = sa.table(
            "role_permissions",
            sa.column("permission_id", U()),
        )
        if connection.dialect.name == "postgresql":
            op.execute(
                'ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY'
            )
        permission_ids = list(
            connection.scalars(
                sa.select(permissions.c.id).where(
                    permissions.c.code.in_(
                        tuple(item[0] for item in PERMISSION_DEFINITIONS)
                    )
                )
            )
        )
        if permission_ids:
            connection.execute(
                role_permissions.delete().where(
                    role_permissions.c.permission_id.in_(permission_ids)
                )
            )
            connection.execute(
                permissions.delete().where(
                    permissions.c.id.in_(permission_ids)
                )
            )
        if connection.dialect.name == "postgresql":
            op.execute(
                'ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY'
            )

    for table in reversed(INVENTORY_TABLES):
        op.drop_table(table)
