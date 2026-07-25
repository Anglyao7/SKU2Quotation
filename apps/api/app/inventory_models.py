from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin, utcnow


class WarehouseRow(AuditTimestampMixin, Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status_allowed"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_warehouses_tenant_identity"),
        UniqueConstraint("tenant_id", "code", name="uq_warehouses_tenant_code"),
        Index("ix_warehouses_tenant_status", "tenant_id", "status"),
        Index(
            "uq_warehouses_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default = true AND deleted_at IS NULL"),
            sqlite_where=text("is_default = 1 AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)


class InventoryBalanceRow(AuditTimestampMixin, Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        CheckConstraint("on_hand_quantity >= 0", name="on_hand_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_nonnegative"),
        CheckConstraint(
            "reserved_quantity <= on_hand_quantity", name="reserved_not_above_on_hand"
        ),
        CheckConstraint("average_cost >= 0", name="average_cost_nonnegative"),
        CheckConstraint("reorder_point >= 0", name="reorder_point_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint(
            "tenant_id", "warehouse_id", "sku_id", name="uq_inventory_balance_location_sku"
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_balances_tenant_identity"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_balances_tenant_warehouse",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_inventory_balances_tenant_sku",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_inventory_balances_tenant_warehouse_stock",
            "tenant_id",
            "warehouse_id",
            "on_hand_quantity",
        ),
        Index("ix_inventory_balances_tenant_sku", "tenant_id", "sku_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    on_hand_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    average_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class PurchaseOrderRow(AuditTimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'PARTIALLY_RECEIVED', 'RECEIVED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_purchase_orders_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "order_number", name="uq_purchase_orders_tenant_number"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_purchase_orders_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_purchase_orders_tenant_creator",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_purchase_orders_tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    order_number: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(300), nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=Decimal("0"), nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PurchaseOrderItemRow(AuditTimestampMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("line_number >= 1", name="line_number_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("received_quantity >= 0", name="received_nonnegative"),
        CheckConstraint(
            "received_quantity <= quantity", name="received_not_above_ordered"
        ),
        CheckConstraint("unit_cost >= 0 AND line_total >= 0", name="amounts_nonnegative"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_purchase_order_items_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id", "purchase_order_id", "line_number", name="uq_purchase_order_items_line"
        ),
        UniqueConstraint(
            "tenant_id", "purchase_order_id", "sku_id", name="uq_purchase_order_items_sku"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "purchase_order_id"],
            ["purchase_orders.tenant_id", "purchase_orders.id"],
            name="fk_purchase_order_items_tenant_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_purchase_order_items_tenant_sku",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SalesOrderRow(AuditTimestampMixin, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'PARTIALLY_SHIPPED', 'SHIPPED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_sales_orders_tenant_identity"),
        UniqueConstraint("tenant_id", "order_number", name="uq_sales_orders_tenant_number"),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_sales_orders_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_sales_orders_tenant_customer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_quotation_id"],
            ["quotations.tenant_id", "quotations.id"],
            name="fk_sales_orders_tenant_quotation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_sales_orders_tenant_creator",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_sales_orders_tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    order_number: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(nullable=True)
    customer_name: Mapped[str] = mapped_column(String(300), nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    source_quotation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=Decimal("0"), nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SalesOrderItemRow(AuditTimestampMixin, Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("line_number >= 1", name="line_number_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_nonnegative"),
        CheckConstraint("shipped_quantity >= 0", name="shipped_nonnegative"),
        CheckConstraint(
            "reserved_quantity + shipped_quantity <= quantity",
            name="fulfilled_not_above_ordered",
        ),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="amounts_nonnegative"),
        UniqueConstraint("tenant_id", "id", name="uq_sales_order_items_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "sales_order_id", "line_number", name="uq_sales_order_items_line"
        ),
        UniqueConstraint(
            "tenant_id", "sales_order_id", "sku_id", name="uq_sales_order_items_sku"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sales_order_id"],
            ["sales_orders.tenant_id", "sales_orders.id"],
            name="fk_sales_order_items_tenant_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_sales_order_items_tenant_sku",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sales_order_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    shipped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 6), default=Decimal("0"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class InventoryDocumentRow(AuditTimestampMixin, Base):
    __tablename__ = "inventory_documents"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('PURCHASE_RECEIPT', 'SALES_RESERVATION', 'SALES_SHIPMENT', "
            "'SALES_RELEASE', 'MANUAL_ADJUSTMENT', 'STOCK_TRANSFER')",
            name="document_type_allowed",
        ),
        CheckConstraint("status = 'POSTED'", name="posted_only"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_documents_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id", "document_number", name="uq_inventory_documents_tenant_number"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_documents_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "counterparty_warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_documents_tenant_counterparty_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_inventory_documents_tenant_creator",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_inventory_documents_tenant_type_occurred",
            "tenant_id",
            "document_type",
            "occurred_at",
        ),
        Index(
            "uq_inventory_documents_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_number: Mapped[str] = mapped_column(String(80), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="POSTED", nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    counterparty_warehouse_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)


class InventoryDocumentItemRow(AuditTimestampMixin, Base):
    __tablename__ = "inventory_document_items"
    __table_args__ = (
        CheckConstraint("line_number >= 1", name="line_number_positive"),
        CheckConstraint("quantity <> 0", name="quantity_nonzero"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_nonnegative"),
        CheckConstraint(
            "NOT (purchase_order_item_id IS NOT NULL AND sales_order_item_id IS NOT NULL)",
            name="single_source_item",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_document_items_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id", "document_id", "line_number", name="uq_inventory_document_items_line"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["inventory_documents.tenant_id", "inventory_documents.id"],
            name="fk_inventory_document_items_tenant_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_inventory_document_items_tenant_sku",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "purchase_order_item_id"],
            ["purchase_order_items.tenant_id", "purchase_order_items.id"],
            name="fk_inventory_document_items_tenant_purchase_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sales_order_item_id"],
            ["sales_order_items.tenant_id", "sales_order_items.id"],
            name="fk_inventory_document_items_tenant_sales_item",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    purchase_order_item_id: Mapped[UUID | None] = mapped_column(nullable=True)
    sales_order_item_id: Mapped[UUID | None] = mapped_column(nullable=True)
    line_number: Mapped[int] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)


class InventoryMovementRow(AuditTimestampMixin, Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('PURCHASE_RECEIPT', 'SALES_RESERVATION', 'SALES_SHIPMENT', "
            "'SALES_RELEASE', 'MANUAL_ADJUSTMENT', 'TRANSFER_OUT', 'TRANSFER_IN')",
            name="movement_type_allowed",
        ),
        CheckConstraint(
            "on_hand_delta <> 0 OR reserved_delta <> 0", name="movement_delta_nonzero"
        ),
        CheckConstraint(
            "on_hand_before >= 0 AND on_hand_after >= 0", name="on_hand_nonnegative"
        ),
        CheckConstraint(
            "reserved_before >= 0 AND reserved_after >= 0", name="reserved_nonnegative"
        ),
        CheckConstraint("average_cost_after >= 0", name="average_cost_nonnegative"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_inventory_movements_tenant_identity"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["inventory_documents.tenant_id", "inventory_documents.id"],
            name="fk_inventory_movements_tenant_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_item_id"],
            ["inventory_document_items.tenant_id", "inventory_document_items.id"],
            name="fk_inventory_movements_tenant_document_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            ["warehouses.tenant_id", "warehouses.id"],
            name="fk_inventory_movements_tenant_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_inventory_movements_tenant_sku",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_inventory_movements_tenant_location_sku_time",
            "tenant_id",
            "warehouse_id",
            "sku_id",
            "occurred_at",
        ),
        Index(
            "ix_inventory_movements_tenant_document",
            "tenant_id",
            "document_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    document_item_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    on_hand_delta: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reserved_delta: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    on_hand_before: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    on_hand_after: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reserved_before: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    reserved_after: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    average_cost_after: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
