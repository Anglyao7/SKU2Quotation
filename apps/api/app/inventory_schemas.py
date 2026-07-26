from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class WarehouseCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=2000)
    currency: str = Field(default="CNY", pattern=r"^[A-Za-z]{3}$")
    is_default: bool = False

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class WarehouseUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=2000)
    status: Literal["ACTIVE", "INACTIVE"] | None = None
    is_default: bool | None = None


class WarehouseResponse(BaseModel):
    id: UUID
    code: str
    name: str
    address: str | None
    currency: str
    status: str
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime


class StockPolicyUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reorder_point: Decimal = Field(ge=0)


class InventoryStockItem(BaseModel):
    balance_id: UUID | None
    warehouse_id: UUID
    warehouse_name: str
    currency: str
    sku_id: UUID
    sku_code: str
    sku_name: str
    product_id: UUID
    product_name: str
    supplier_id: str | None
    supplier_name: str | None
    on_hand_quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal
    average_cost: Decimal
    inventory_value: Decimal
    reorder_point: Decimal
    low_stock: bool
    version: int
    updated_at: datetime | None


class InventoryStockPage(BaseModel):
    items: list[InventoryStockItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class InventoryOverviewResponse(BaseModel):
    warehouse_id: UUID
    warehouse_name: str
    currency: str
    total_skus: int = Field(ge=0)
    stocked_skus: int = Field(ge=0)
    on_hand_quantity: Decimal
    reserved_quantity: Decimal
    available_quantity: Decimal
    inventory_value: Decimal
    low_stock_count: int = Field(ge=0)
    open_purchase_orders: int = Field(ge=0)
    open_sales_orders: int = Field(ge=0)
    low_stock_items: list[InventoryStockItem]


class InventoryMovementResponse(BaseModel):
    id: UUID
    document_id: UUID
    document_number: str
    document_type: str
    source_number: str | None
    warehouse_id: UUID
    warehouse_name: str
    currency: str
    sku_id: UUID
    sku_code: str
    sku_name: str
    movement_type: str
    on_hand_delta: Decimal
    reserved_delta: Decimal
    on_hand_after: Decimal
    reserved_after: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    average_cost_after: Decimal
    notes: str | None
    occurred_at: datetime


class InventoryMovementPage(BaseModel):
    items: list[InventoryMovementResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class InventoryDocumentItemResponse(BaseModel):
    id: UUID
    sku_id: UUID
    sku_code: str
    sku_name: str
    quantity: Decimal
    unit_cost: Decimal | None


class InventoryDocumentResponse(BaseModel):
    id: UUID
    document_number: str
    document_type: str
    warehouse_id: UUID
    counterparty_warehouse_id: UUID | None
    source_type: str | None
    source_id: UUID | None
    source_number: str | None
    notes: str | None
    occurred_at: datetime
    items: list[InventoryDocumentItemResponse]


class PurchaseOrderLineCreate(BaseModel):
    sku_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class PurchaseOrderCreateRequest(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=300)
    warehouse_id: UUID | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    expected_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    items: list[PurchaseOrderLineCreate] = Field(min_length=1, max_length=500)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def unique_skus(self) -> "PurchaseOrderCreateRequest":
        sku_ids = [item.sku_id for item in self.items]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("purchase order items must use unique SKU values")
        return self


class PurchaseOrderItemResponse(BaseModel):
    id: UUID
    sku_id: UUID
    sku_code: str
    sku_name: str
    quantity: Decimal
    received_quantity: Decimal
    remaining_quantity: Decimal
    unit_cost: Decimal
    line_total: Decimal
    notes: str | None


class PurchaseOrderSummary(BaseModel):
    id: UUID
    order_number: str
    supplier_name: str
    warehouse_id: UUID
    warehouse_name: str
    currency: str
    status: str
    total_amount: Decimal
    expected_at: datetime | None
    version: int
    updated_at: datetime


class PurchaseOrderResponse(PurchaseOrderSummary):
    notes: str | None
    confirmed_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    items: list[PurchaseOrderItemResponse]


class OrderActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class PurchaseReceiptLine(BaseModel):
    order_item_id: UUID
    quantity: Decimal = Field(gt=0)


class PurchaseReceiptRequest(BaseModel):
    expected_version: int = Field(ge=1)
    occurred_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    items: list[PurchaseReceiptLine] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_items(self) -> "PurchaseReceiptRequest":
        item_ids = [item.order_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("receipt items must be unique")
        return self


class SalesOrderLineCreate(BaseModel):
    sku_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class SalesOrderCreateRequest(BaseModel):
    customer_id: UUID | None = None
    customer_name: str = Field(min_length=1, max_length=300)
    warehouse_id: UUID | None = None
    source_quotation_id: UUID | None = None
    currency: str = Field(default="CNY", pattern=r"^[A-Za-z]{3}$")
    notes: str | None = Field(default=None, max_length=2000)
    items: list[SalesOrderLineCreate] = Field(min_length=1, max_length=500)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def unique_skus(self) -> "SalesOrderCreateRequest":
        sku_ids = [item.sku_id for item in self.items]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("sales order items must use unique SKU values")
        return self


class SalesOrderItemResponse(BaseModel):
    id: UUID
    sku_id: UUID
    sku_code: str
    sku_name: str
    quantity: Decimal
    reserved_quantity: Decimal
    shipped_quantity: Decimal
    remaining_quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    cost_amount: Decimal
    notes: str | None


class SalesOrderSummary(BaseModel):
    id: UUID
    order_number: str
    customer_name: str
    warehouse_id: UUID
    warehouse_name: str
    currency: str
    status: str
    total_amount: Decimal
    version: int
    updated_at: datetime


class SalesOrderResponse(SalesOrderSummary):
    customer_id: UUID | None
    source_quotation_id: UUID | None
    notes: str | None
    confirmed_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    items: list[SalesOrderItemResponse]


class SalesShipmentLine(BaseModel):
    order_item_id: UUID
    quantity: Decimal = Field(gt=0)


class SalesShipmentRequest(BaseModel):
    expected_version: int = Field(ge=1)
    occurred_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    items: list[SalesShipmentLine] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_items(self) -> "SalesShipmentRequest":
        item_ids = [item.order_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("shipment items must be unique")
        return self


class InventoryAdjustmentLine(BaseModel):
    sku_id: UUID
    quantity_delta: Decimal
    unit_cost: Decimal | None = Field(default=None, ge=0)

    @field_validator("quantity_delta")
    @classmethod
    def quantity_must_change(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("quantity_delta must not be zero")
        return value


class InventoryAdjustmentRequest(BaseModel):
    warehouse_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=1000)
    occurred_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    items: list[InventoryAdjustmentLine] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_skus(self) -> "InventoryAdjustmentRequest":
        sku_ids = [item.sku_id for item in self.items]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("adjustment items must use unique SKU values")
        return self


class StockTransferLine(BaseModel):
    sku_id: UUID
    quantity: Decimal = Field(gt=0)


class StockTransferRequest(BaseModel):
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    reason: str = Field(min_length=3, max_length=1000)
    occurred_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    items: list[StockTransferLine] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_transfer(self) -> "StockTransferRequest":
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("source and destination warehouses must differ")
        sku_ids = [item.sku_id for item in self.items]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("transfer items must use unique SKU values")
        return self
