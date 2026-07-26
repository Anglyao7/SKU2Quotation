from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..inventory_models import (
    InventoryBalanceRow,
    InventoryDocumentItemRow,
    InventoryDocumentRow,
    InventoryMovementRow,
    PurchaseOrderItemRow,
    PurchaseOrderRow,
    SalesOrderItemRow,
    SalesOrderRow,
    WarehouseRow,
)
from ..inventory_schemas import (
    InventoryAdjustmentRequest,
    InventoryDocumentItemResponse,
    InventoryDocumentResponse,
    InventoryMovementPage,
    InventoryMovementResponse,
    InventoryOverviewResponse,
    InventoryStockItem,
    InventoryStockPage,
    OrderActionRequest,
    PurchaseOrderCreateRequest,
    PurchaseOrderItemResponse,
    PurchaseOrderResponse,
    PurchaseOrderSummary,
    PurchaseReceiptRequest,
    SalesOrderCreateRequest,
    SalesOrderItemResponse,
    SalesOrderResponse,
    SalesOrderSummary,
    SalesShipmentRequest,
    StockPolicyUpdateRequest,
    StockTransferRequest,
    WarehouseCreateRequest,
    WarehouseResponse,
    WarehouseUpdateRequest,
)
from ..inventory_seed import ensure_default_warehouse
from ..model_mixins import utcnow
from ..repositories import inventory_repository as repository


ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.000001")


def _require(permissions: frozenset[str], permission: str) -> None:
    if permission not in permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            f"Permission required: {permission}",
            kind="forbidden",
        )


def _commit(session: Session, *, code: str, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(code, message, kind="conflict") from exc


def _quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _number(prefix: str) -> str:
    return f"{prefix}-{utcnow():%Y%m%d}-{uuid4().hex[:8].upper()}"


def _warehouse_response(row: WarehouseRow) -> WarehouseResponse:
    return WarehouseResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        address=row.address,
        currency=row.currency,
        status=row.status,
        is_default=row.is_default,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _active_warehouse(
    session: Session,
    *,
    tenant_id: UUID,
    warehouse_id: UUID | None,
    membership_id: UUID | None = None,
) -> WarehouseRow:
    if warehouse_id is None:
        warehouse = repository.get_default_warehouse(session, tenant_id=tenant_id)
        if warehouse is None:
            warehouse = ensure_default_warehouse(
                session,
                tenant_id=tenant_id,
                created_by_membership_id=membership_id,
            )
            session.commit()
    else:
        warehouse = repository.get_warehouse(
            session, tenant_id=tenant_id, warehouse_id=warehouse_id
        )
    if warehouse is None:
        raise ApplicationError(
            "WAREHOUSE_NOT_FOUND", "Warehouse was not found.", kind="not_found"
        )
    if warehouse.status != "ACTIVE":
        raise ApplicationError(
            "WAREHOUSE_INACTIVE", "The selected warehouse is inactive.", kind="conflict"
        )
    return warehouse


def list_warehouses(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
) -> list[WarehouseResponse]:
    _require(permissions, "inventory.view")
    rows = repository.list_warehouses(session, tenant_id=tenant_id)
    if not rows:
        ensure_default_warehouse(
            session,
            tenant_id=tenant_id,
            created_by_membership_id=membership_id,
        )
        session.commit()
        rows = repository.list_warehouses(session, tenant_id=tenant_id)
    return [_warehouse_response(row) for row in rows]


def create_warehouse(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: WarehouseCreateRequest,
) -> WarehouseResponse:
    _require(permissions, "inventory.warehouse_manage")
    existing = repository.list_warehouses(session, tenant_id=tenant_id)
    if any(row.code.casefold() == request.code.casefold() for row in existing):
        raise ApplicationError(
            "WAREHOUSE_CODE_EXISTS",
            "Warehouse code is already in use.",
            kind="conflict",
        )
    is_default = request.is_default or not any(
        row.is_default and row.status == "ACTIVE" for row in existing
    )
    if is_default:
        repository.clear_default_warehouse(session, tenant_id=tenant_id)
    row = WarehouseRow(
        tenant_id=tenant_id,
        code=request.code,
        name=request.name.strip(),
        address=request.address.strip() if request.address else None,
        currency=request.currency,
        status="ACTIVE",
        is_default=is_default,
        created_by_membership_id=membership_id,
    )
    session.add(row)
    _commit(
        session,
        code="WAREHOUSE_CODE_EXISTS",
        message="Warehouse code is already in use.",
    )
    return _warehouse_response(row)


def update_warehouse(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    warehouse_id: UUID,
    request: WarehouseUpdateRequest,
) -> WarehouseResponse:
    _require(permissions, "inventory.warehouse_manage")
    row = repository.get_warehouse_for_update(
        session, tenant_id=tenant_id, warehouse_id=warehouse_id
    )
    if row is None:
        raise ApplicationError(
            "WAREHOUSE_NOT_FOUND", "Warehouse was not found.", kind="not_found"
        )
    if row.version != request.expected_version:
        raise ApplicationError(
            "VERSION_CONFLICT",
            "Warehouse changed; refresh before saving.",
            kind="conflict",
        )
    if request.status == "INACTIVE":
        if row.is_default:
            raise ApplicationError(
                "DEFAULT_WAREHOUSE_REQUIRED",
                "Choose another default warehouse before deactivating this one.",
                kind="conflict",
            )
        if repository.warehouse_has_stock_or_reservations(
            session, tenant_id=tenant_id, warehouse_id=row.id
        ):
            raise ApplicationError(
                "WAREHOUSE_NOT_EMPTY",
                "Move or clear all stock before deactivating this warehouse.",
                kind="conflict",
            )
    if request.is_default is False and row.is_default:
        raise ApplicationError(
            "DEFAULT_WAREHOUSE_REQUIRED",
            "Set another warehouse as default instead of clearing the only default.",
            kind="conflict",
        )
    if request.is_default is True:
        if request.status == "INACTIVE" or row.status == "INACTIVE":
            raise ApplicationError(
                "DEFAULT_WAREHOUSE_INACTIVE",
                "An inactive warehouse cannot be the default.",
                kind="conflict",
            )
        repository.clear_default_warehouse(
            session, tenant_id=tenant_id, except_id=row.id
        )
        row.is_default = True
    if request.name is not None:
        row.name = request.name.strip()
    if "address" in request.model_fields_set:
        row.address = request.address.strip() if request.address else None
    if request.status is not None:
        row.status = request.status
    row.version += 1
    session.commit()
    return _warehouse_response(row)


def _stock_response(
    *,
    warehouse: WarehouseRow,
    sku: object,
    product: object,
    supplier: object | None,
    balance: InventoryBalanceRow | None,
) -> InventoryStockItem:
    on_hand = balance.on_hand_quantity if balance is not None else ZERO
    reserved = balance.reserved_quantity if balance is not None else ZERO
    average_cost = balance.average_cost if balance is not None else ZERO
    reorder_point = balance.reorder_point if balance is not None else ZERO
    available = on_hand - reserved
    return InventoryStockItem(
        balance_id=balance.id if balance is not None else None,
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        currency=warehouse.currency,
        sku_id=sku.id,
        sku_code=sku.sku_code,
        sku_name=sku.name or product.name,
        product_id=product.id,
        product_name=product.name,
        supplier_id=supplier.id if supplier is not None else None,
        supplier_name=supplier.name if supplier is not None else None,
        on_hand_quantity=on_hand,
        reserved_quantity=reserved,
        available_quantity=available,
        average_cost=average_cost,
        inventory_value=_money(on_hand * average_cost),
        reorder_point=reorder_point,
        low_stock=reorder_point > 0 and available <= reorder_point,
        version=balance.version if balance is not None else 1,
        updated_at=balance.updated_at if balance is not None else None,
    )


def list_stock(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    warehouse_id: UUID | None,
    query: str,
    low_stock_only: bool,
    page: int,
    page_size: int,
) -> InventoryStockPage:
    _require(permissions, "inventory.view")
    warehouse = _active_warehouse(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        membership_id=membership_id,
    )
    rows, total = repository.list_stock_rows(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse.id,
        query=query,
        low_stock_only=low_stock_only,
        page=page,
        page_size=page_size,
    )
    return InventoryStockPage(
        items=[
            _stock_response(
                warehouse=warehouse,
                sku=row.sku,
                product=row.product,
                supplier=row.supplier,
                balance=row.balance,
            )
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
        pages=ceil(total / page_size) if total else 0,
    )


def inventory_overview(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    warehouse_id: UUID | None,
) -> InventoryOverviewResponse:
    _require(permissions, "inventory.view")
    warehouse = _active_warehouse(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        membership_id=membership_id,
    )
    aggregates = repository.inventory_aggregates(
        session, tenant_id=tenant_id, warehouse_id=warehouse.id
    )
    low_rows, _ = repository.list_stock_rows(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse.id,
        query="",
        low_stock_only=True,
        page=1,
        page_size=8,
    )
    on_hand = Decimal(aggregates["on_hand_quantity"])
    reserved = Decimal(aggregates["reserved_quantity"])
    return InventoryOverviewResponse(
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        currency=warehouse.currency,
        total_skus=int(aggregates["total_skus"]),
        stocked_skus=int(aggregates["stocked_skus"]),
        on_hand_quantity=on_hand,
        reserved_quantity=reserved,
        available_quantity=on_hand - reserved,
        inventory_value=Decimal(aggregates["inventory_value"]),
        low_stock_count=int(aggregates["low_stock_count"]),
        open_purchase_orders=int(aggregates["open_purchase_orders"]),
        open_sales_orders=int(aggregates["open_sales_orders"]),
        low_stock_items=[
            _stock_response(
                warehouse=warehouse,
                sku=row.sku,
                product=row.product,
                supplier=row.supplier,
                balance=row.balance,
            )
            for row in low_rows
        ],
    )


def _ensure_balance(
    session: Session,
    *,
    tenant_id: UUID,
    warehouse_id: UUID,
    sku_id: UUID,
) -> InventoryBalanceRow:
    row = repository.get_balance_for_update(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
    )
    if row is None:
        row = InventoryBalanceRow(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            on_hand_quantity=ZERO,
            reserved_quantity=ZERO,
            average_cost=ZERO,
            reorder_point=ZERO,
            version=1,
        )
        session.add(row)
        session.flush()
    return row


def update_stock_policy(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    warehouse_id: UUID,
    sku_id: UUID,
    request: StockPolicyUpdateRequest,
) -> InventoryStockItem:
    _require(permissions, "inventory.adjust")
    warehouse = _active_warehouse(
        session, tenant_id=tenant_id, warehouse_id=warehouse_id
    )
    sku_rows = repository.get_skus(session, tenant_id=tenant_id, sku_ids={sku_id})
    sku_pair = sku_rows.get(sku_id)
    if sku_pair is None:
        raise ApplicationError("SKU_NOT_FOUND", "SKU was not found.", kind="not_found")
    balance = repository.get_balance_for_update(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse.id,
        sku_id=sku_id,
    )
    if balance is None:
        if request.expected_version != 1:
            raise ApplicationError(
                "VERSION_CONFLICT",
                "Stock policy changed; refresh before saving.",
                kind="conflict",
            )
        balance = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            sku_id=sku_id,
        )
    elif balance.version != request.expected_version:
        raise ApplicationError(
            "VERSION_CONFLICT",
            "Stock policy changed; refresh before saving.",
            kind="conflict",
        )
    balance.reorder_point = _quantity(request.reorder_point)
    balance.version += 1
    session.commit()
    sku, product = sku_pair
    supplier = repository.get_supplier(
        session,
        tenant_id=tenant_id,
        supplier_id=sku.supplier_id,
    )
    return _stock_response(
        warehouse=warehouse,
        sku=sku,
        product=product,
        supplier=supplier,
        balance=balance,
    )


def _new_document(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    prefix: str,
    document_type: str,
    warehouse_id: UUID,
    counterparty_warehouse_id: UUID | None = None,
    source_type: str | None = None,
    source_id: UUID | None = None,
    source_number: str | None = None,
    idempotency_key: str | None = None,
    notes: str | None = None,
    occurred_at: datetime | None = None,
) -> InventoryDocumentRow:
    row = InventoryDocumentRow(
        tenant_id=tenant_id,
        document_number=_number(prefix),
        document_type=document_type,
        status="POSTED",
        warehouse_id=warehouse_id,
        counterparty_warehouse_id=counterparty_warehouse_id,
        source_type=source_type,
        source_id=source_id,
        source_number=source_number,
        idempotency_key=idempotency_key,
        notes=notes,
        occurred_at=occurred_at or utcnow(),
        created_by_membership_id=membership_id,
    )
    session.add(row)
    session.flush()
    return row


def _apply_movement(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    balance: InventoryBalanceRow,
    document: InventoryDocumentRow,
    document_item: InventoryDocumentItemRow,
    movement_type: str,
    on_hand_delta: Decimal,
    reserved_delta: Decimal,
    inbound_unit_cost: Decimal | None = None,
) -> InventoryMovementRow:
    on_hand_delta = _quantity(on_hand_delta)
    reserved_delta = _quantity(reserved_delta)
    before_on_hand = balance.on_hand_quantity
    before_reserved = balance.reserved_quantity
    after_on_hand = _quantity(before_on_hand + on_hand_delta)
    after_reserved = _quantity(before_reserved + reserved_delta)
    if after_on_hand < 0 or after_reserved < 0 or after_reserved > after_on_hand:
        raise ApplicationError(
            "INSUFFICIENT_AVAILABLE_STOCK",
            "Available stock is insufficient for this operation.",
            kind="conflict",
        )

    unit_cost = balance.average_cost
    average_cost = balance.average_cost
    if on_hand_delta > 0:
        unit_cost = inbound_unit_cost if inbound_unit_cost is not None else balance.average_cost
        unit_cost = _quantity(unit_cost)
        if after_on_hand > 0:
            average_cost = _quantity(
                (
                    before_on_hand * balance.average_cost
                    + on_hand_delta * unit_cost
                )
                / after_on_hand
            )
    elif on_hand_delta < 0:
        unit_cost = balance.average_cost

    balance.on_hand_quantity = after_on_hand
    balance.reserved_quantity = after_reserved
    balance.average_cost = average_cost
    balance.version += 1
    movement = InventoryMovementRow(
        tenant_id=tenant_id,
        document_id=document.id,
        document_item_id=document_item.id,
        warehouse_id=balance.warehouse_id,
        sku_id=balance.sku_id,
        movement_type=movement_type,
        on_hand_delta=on_hand_delta,
        reserved_delta=reserved_delta,
        on_hand_before=before_on_hand,
        on_hand_after=after_on_hand,
        reserved_before=before_reserved,
        reserved_after=after_reserved,
        unit_cost=unit_cost,
        total_cost=_quantity(on_hand_delta * unit_cost),
        average_cost_after=average_cost,
        occurred_at=document.occurred_at,
        created_by_membership_id=membership_id,
    )
    session.add(movement)
    return movement


def _idempotent_document(
    session: Session,
    *,
    tenant_id: UUID,
    idempotency_key: str | None,
    document_type: str,
    source_id: UUID | None,
) -> InventoryDocumentRow | None:
    if not idempotency_key:
        return None
    row = repository.get_document_by_idempotency(
        session, tenant_id=tenant_id, idempotency_key=idempotency_key
    )
    if row is None:
        return None
    if row.document_type != document_type or row.source_id != source_id:
        raise ApplicationError(
            "IDEMPOTENCY_KEY_REUSED",
            "This idempotency key was already used for another stock document.",
            kind="conflict",
        )
    return row


def _document_response(
    session: Session, *, tenant_id: UUID, document: InventoryDocumentRow
) -> InventoryDocumentResponse:
    items = repository.list_document_items(
        session, tenant_id=tenant_id, document_id=document.id
    )
    return InventoryDocumentResponse(
        id=document.id,
        document_number=document.document_number,
        document_type=document.document_type,
        warehouse_id=document.warehouse_id,
        counterparty_warehouse_id=document.counterparty_warehouse_id,
        source_type=document.source_type,
        source_id=document.source_id,
        source_number=document.source_number,
        notes=document.notes,
        occurred_at=document.occurred_at,
        items=[
            InventoryDocumentItemResponse(
                id=item.id,
                sku_id=sku.id,
                sku_code=sku.sku_code,
                sku_name=sku.name or product.name,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
            )
            for item, sku, product in items
        ],
    )


def _movement_response(row: repository.MovementQueryRow) -> InventoryMovementResponse:
    return InventoryMovementResponse(
        id=row.movement.id,
        document_id=row.document.id,
        document_number=row.document.document_number,
        document_type=row.document.document_type,
        source_number=row.document.source_number,
        warehouse_id=row.warehouse.id,
        warehouse_name=row.warehouse.name,
        currency=row.warehouse.currency,
        sku_id=row.sku.id,
        sku_code=row.sku.sku_code,
        sku_name=row.sku.name or row.product.name,
        movement_type=row.movement.movement_type,
        on_hand_delta=row.movement.on_hand_delta,
        reserved_delta=row.movement.reserved_delta,
        on_hand_after=row.movement.on_hand_after,
        reserved_after=row.movement.reserved_after,
        unit_cost=row.movement.unit_cost,
        total_cost=row.movement.total_cost,
        average_cost_after=row.movement.average_cost_after,
        notes=row.document.notes,
        occurred_at=row.movement.occurred_at,
    )


def list_movements(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    warehouse_id: UUID | None,
    query: str,
    movement_type: str | None,
    page: int,
    page_size: int,
) -> InventoryMovementPage:
    _require(permissions, "inventory.view")
    rows, total = repository.list_movements(
        session,
        tenant_id=tenant_id,
        warehouse_id=warehouse_id,
        query=query,
        movement_type=movement_type,
        page=page,
        page_size=page_size,
    )
    return InventoryMovementPage(
        items=[_movement_response(row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        pages=ceil(total / page_size) if total else 0,
    )


def _purchase_response(
    session: Session,
    *,
    tenant_id: UUID,
    order: PurchaseOrderRow,
    warehouse: WarehouseRow,
) -> PurchaseOrderResponse:
    items = repository.list_purchase_order_items(
        session, tenant_id=tenant_id, order_id=order.id
    )
    return PurchaseOrderResponse(
        id=order.id,
        order_number=order.order_number,
        supplier_name=order.supplier_name,
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        currency=order.currency,
        status=order.status,
        total_amount=order.total_amount,
        expected_at=order.expected_at,
        version=order.version,
        updated_at=order.updated_at,
        notes=order.notes,
        confirmed_at=order.confirmed_at,
        completed_at=order.completed_at,
        created_at=order.created_at,
        items=[
            PurchaseOrderItemResponse(
                id=item.id,
                sku_id=sku.id,
                sku_code=sku.sku_code,
                sku_name=sku.name or product.name,
                quantity=item.quantity,
                received_quantity=item.received_quantity,
                remaining_quantity=item.quantity - item.received_quantity,
                unit_cost=item.unit_cost,
                line_total=item.line_total,
                notes=item.notes,
            )
            for item, sku, product in items
        ],
    )


def list_purchase_orders(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    status: str | None,
    limit: int,
) -> list[PurchaseOrderSummary]:
    _require(permissions, "inventory.view")
    return [
        PurchaseOrderSummary(
            id=order.id,
            order_number=order.order_number,
            supplier_name=order.supplier_name,
            warehouse_id=warehouse.id,
            warehouse_name=warehouse.name,
            currency=order.currency,
            status=order.status,
            total_amount=order.total_amount,
            expected_at=order.expected_at,
            version=order.version,
            updated_at=order.updated_at,
        )
        for order, warehouse in repository.list_purchase_orders(
            session,
            tenant_id=tenant_id,
            status=status.upper() if status else None,
            limit=limit,
        )
    ]


def create_purchase_order(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: PurchaseOrderCreateRequest,
) -> PurchaseOrderResponse:
    _require(permissions, "inventory.purchase")
    warehouse = _active_warehouse(
        session,
        tenant_id=tenant_id,
        warehouse_id=request.warehouse_id,
        membership_id=membership_id,
    )
    currency = request.currency or warehouse.currency
    if currency != warehouse.currency:
        raise ApplicationError(
            "PURCHASE_CURRENCY_MISMATCH",
            "Purchase currency must match the warehouse valuation currency.",
            kind="conflict",
        )
    sku_ids = {item.sku_id for item in request.items}
    sku_rows = repository.get_skus(session, tenant_id=tenant_id, sku_ids=sku_ids)
    if len(sku_rows) != len(sku_ids):
        raise ApplicationError("SKU_NOT_FOUND", "One or more SKUs were not found.", kind="not_found")
    if any(sku.status == "ARCHIVED" for sku, _ in sku_rows.values()):
        raise ApplicationError(
            "SKU_ARCHIVED", "Archived SKUs cannot be purchased.", kind="conflict"
        )
    total = sum((_money(item.quantity * item.unit_cost) for item in request.items), ZERO)
    order = PurchaseOrderRow(
        tenant_id=tenant_id,
        order_number=_number("PO"),
        supplier_name=request.supplier_name.strip(),
        warehouse_id=warehouse.id,
        currency=currency,
        status="DRAFT",
        expected_at=request.expected_at,
        notes=request.notes.strip() if request.notes else None,
        total_amount=total,
        version=1,
        created_by_membership_id=membership_id,
    )
    session.add(order)
    session.flush()
    for line_number, item in enumerate(request.items, 1):
        session.add(
            PurchaseOrderItemRow(
                tenant_id=tenant_id,
                purchase_order_id=order.id,
                sku_id=item.sku_id,
                line_number=line_number,
                quantity=_quantity(item.quantity),
                received_quantity=ZERO,
                unit_cost=_quantity(item.unit_cost),
                line_total=_money(item.quantity * item.unit_cost),
                notes=item.notes.strip() if item.notes else None,
            )
        )
    _commit(
        session,
        code="PURCHASE_ORDER_CONFLICT",
        message="Purchase order could not be created because its data conflicts.",
    )
    return _purchase_response(
        session, tenant_id=tenant_id, order=order, warehouse=warehouse
    )


def get_purchase_order(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
) -> PurchaseOrderResponse:
    _require(permissions, "inventory.view")
    result = repository.get_purchase_order(
        session, tenant_id=tenant_id, order_id=order_id
    )
    if result is None:
        raise ApplicationError(
            "PURCHASE_ORDER_NOT_FOUND", "Purchase order was not found.", kind="not_found"
        )
    order, warehouse = result
    return _purchase_response(
        session, tenant_id=tenant_id, order=order, warehouse=warehouse
    )


def confirm_purchase_order(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
    request: OrderActionRequest,
) -> PurchaseOrderResponse:
    _require(permissions, "inventory.purchase")
    result = repository.get_purchase_order(
        session, tenant_id=tenant_id, order_id=order_id, for_update=True
    )
    if result is None:
        raise ApplicationError(
            "PURCHASE_ORDER_NOT_FOUND", "Purchase order was not found.", kind="not_found"
        )
    order, warehouse = result
    if order.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Purchase order changed; refresh first.", kind="conflict")
    if order.status != "DRAFT":
        raise ApplicationError(
            "PURCHASE_ORDER_STATE_INVALID",
            "Only draft purchase orders can be confirmed.",
            kind="conflict",
        )
    order.status = "CONFIRMED"
    order.confirmed_at = utcnow()
    order.version += 1
    session.commit()
    return _purchase_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def receive_purchase_order(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
    request: PurchaseReceiptRequest,
) -> PurchaseOrderResponse:
    _require(permissions, "inventory.purchase")
    duplicate = _idempotent_document(
        session,
        tenant_id=tenant_id,
        idempotency_key=request.idempotency_key,
        document_type="PURCHASE_RECEIPT",
        source_id=order_id,
    )
    result = repository.get_purchase_order(
        session, tenant_id=tenant_id, order_id=order_id, for_update=True
    )
    if result is None:
        raise ApplicationError(
            "PURCHASE_ORDER_NOT_FOUND", "Purchase order was not found.", kind="not_found"
        )
    order, warehouse = result
    if duplicate is not None:
        return _purchase_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)
    if order.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Purchase order changed; refresh first.", kind="conflict")
    if order.status not in {"CONFIRMED", "PARTIALLY_RECEIVED"}:
        raise ApplicationError(
            "PURCHASE_ORDER_STATE_INVALID",
            "Only confirmed purchase orders can receive stock.",
            kind="conflict",
        )
    item_rows = repository.list_purchase_order_items(
        session, tenant_id=tenant_id, order_id=order.id
    )
    items_by_id = {item.id: item for item, _sku, _product in item_rows}
    for line in request.items:
        item = items_by_id.get(line.order_item_id)
        if item is None:
            raise ApplicationError(
                "PURCHASE_ITEM_NOT_FOUND",
                "A receipt line does not belong to this purchase order.",
                kind="not_found",
            )
        if line.quantity > item.quantity - item.received_quantity:
            raise ApplicationError(
                "PURCHASE_RECEIPT_EXCEEDS_REMAINING",
                "Receipt quantity exceeds the remaining purchase quantity.",
                kind="conflict",
            )
    document = _new_document(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        prefix="PR",
        document_type="PURCHASE_RECEIPT",
        warehouse_id=warehouse.id,
        source_type="PURCHASE_ORDER",
        source_id=order.id,
        source_number=order.order_number,
        idempotency_key=request.idempotency_key,
        notes=request.notes.strip() if request.notes else None,
        occurred_at=request.occurred_at,
    )
    for line_number, line in enumerate(request.items, 1):
        item = items_by_id[line.order_item_id]
        document_item = InventoryDocumentItemRow(
            tenant_id=tenant_id,
            document_id=document.id,
            sku_id=item.sku_id,
            purchase_order_item_id=item.id,
            line_number=line_number,
            quantity=_quantity(line.quantity),
            unit_cost=item.unit_cost,
        )
        session.add(document_item)
        session.flush()
        balance = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            sku_id=item.sku_id,
        )
        _apply_movement(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            balance=balance,
            document=document,
            document_item=document_item,
            movement_type="PURCHASE_RECEIPT",
            on_hand_delta=line.quantity,
            reserved_delta=ZERO,
            inbound_unit_cost=item.unit_cost,
        )
        item.received_quantity = _quantity(item.received_quantity + line.quantity)
    all_received = all(item.received_quantity == item.quantity for item in items_by_id.values())
    order.status = "RECEIVED" if all_received else "PARTIALLY_RECEIVED"
    order.completed_at = document.occurred_at if all_received else None
    order.version += 1
    _commit(
        session,
        code="PURCHASE_RECEIPT_CONFLICT",
        message="Purchase receipt could not be posted. Refresh the order and retry.",
    )
    return _purchase_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def cancel_purchase_order(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
    request: OrderActionRequest,
) -> PurchaseOrderResponse:
    _require(permissions, "inventory.purchase")
    result = repository.get_purchase_order(
        session, tenant_id=tenant_id, order_id=order_id, for_update=True
    )
    if result is None:
        raise ApplicationError(
            "PURCHASE_ORDER_NOT_FOUND", "Purchase order was not found.", kind="not_found"
        )
    order, warehouse = result
    if order.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Purchase order changed; refresh first.", kind="conflict")
    if order.status in {"RECEIVED", "CANCELLED"}:
        raise ApplicationError(
            "PURCHASE_ORDER_STATE_INVALID",
            "Completed or cancelled purchase orders cannot be cancelled again.",
            kind="conflict",
        )
    order.status = "CANCELLED"
    order.completed_at = utcnow()
    if request.reason:
        order.notes = "\n".join(filter(None, [order.notes, f"取消原因：{request.reason.strip()}"]))
    order.version += 1
    session.commit()
    return _purchase_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def _sales_response(
    session: Session,
    *,
    tenant_id: UUID,
    order: SalesOrderRow,
    warehouse: WarehouseRow,
) -> SalesOrderResponse:
    items = repository.list_sales_order_items(
        session, tenant_id=tenant_id, order_id=order.id
    )
    return SalesOrderResponse(
        id=order.id,
        order_number=order.order_number,
        customer_name=order.customer_name,
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        currency=order.currency,
        status=order.status,
        total_amount=order.total_amount,
        version=order.version,
        updated_at=order.updated_at,
        customer_id=order.customer_id,
        source_quotation_id=order.source_quotation_id,
        notes=order.notes,
        confirmed_at=order.confirmed_at,
        completed_at=order.completed_at,
        created_at=order.created_at,
        items=[
            SalesOrderItemResponse(
                id=item.id,
                sku_id=sku.id,
                sku_code=sku.sku_code,
                sku_name=sku.name or product.name,
                quantity=item.quantity,
                reserved_quantity=item.reserved_quantity,
                shipped_quantity=item.shipped_quantity,
                remaining_quantity=item.quantity - item.shipped_quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
                cost_amount=item.cost_amount,
                notes=item.notes,
            )
            for item, sku, product in items
        ],
    )


def list_sales_orders(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    status: str | None,
    limit: int,
) -> list[SalesOrderSummary]:
    _require(permissions, "inventory.view")
    return [
        SalesOrderSummary(
            id=order.id,
            order_number=order.order_number,
            customer_name=order.customer_name,
            warehouse_id=warehouse.id,
            warehouse_name=warehouse.name,
            currency=order.currency,
            status=order.status,
            total_amount=order.total_amount,
            version=order.version,
            updated_at=order.updated_at,
        )
        for order, warehouse in repository.list_sales_orders(
            session,
            tenant_id=tenant_id,
            status=status.upper() if status else None,
            limit=limit,
        )
    ]


def create_sales_order(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: SalesOrderCreateRequest,
) -> SalesOrderResponse:
    _require(permissions, "inventory.sale")
    warehouse = _active_warehouse(
        session,
        tenant_id=tenant_id,
        warehouse_id=request.warehouse_id,
        membership_id=membership_id,
    )
    sku_ids = {item.sku_id for item in request.items}
    sku_rows = repository.get_skus(session, tenant_id=tenant_id, sku_ids=sku_ids)
    if len(sku_rows) != len(sku_ids):
        raise ApplicationError("SKU_NOT_FOUND", "One or more SKUs were not found.", kind="not_found")
    if request.customer_id and repository.get_customer(
        session, tenant_id=tenant_id, customer_id=request.customer_id
    ) is None:
        raise ApplicationError("CUSTOMER_NOT_FOUND", "Customer was not found.", kind="not_found")
    if request.source_quotation_id and repository.get_quotation(
        session, tenant_id=tenant_id, quotation_id=request.source_quotation_id
    ) is None:
        raise ApplicationError("QUOTATION_NOT_FOUND", "Quotation was not found.", kind="not_found")
    total = sum((_money(item.quantity * item.unit_price) for item in request.items), ZERO)
    order = SalesOrderRow(
        tenant_id=tenant_id,
        order_number=_number("SO"),
        customer_id=request.customer_id,
        customer_name=request.customer_name.strip(),
        warehouse_id=warehouse.id,
        source_quotation_id=request.source_quotation_id,
        currency=request.currency,
        status="DRAFT",
        notes=request.notes.strip() if request.notes else None,
        total_amount=total,
        version=1,
        created_by_membership_id=membership_id,
    )
    session.add(order)
    session.flush()
    for line_number, item in enumerate(request.items, 1):
        session.add(
            SalesOrderItemRow(
                tenant_id=tenant_id,
                sales_order_id=order.id,
                sku_id=item.sku_id,
                line_number=line_number,
                quantity=_quantity(item.quantity),
                reserved_quantity=ZERO,
                shipped_quantity=ZERO,
                unit_price=_quantity(item.unit_price),
                line_total=_money(item.quantity * item.unit_price),
                cost_amount=ZERO,
                notes=item.notes.strip() if item.notes else None,
            )
        )
    _commit(
        session,
        code="SALES_ORDER_CONFLICT",
        message="Sales order could not be created because its data conflicts.",
    )
    return _sales_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def get_sales_order(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
) -> SalesOrderResponse:
    _require(permissions, "inventory.view")
    result = repository.get_sales_order(session, tenant_id=tenant_id, order_id=order_id)
    if result is None:
        raise ApplicationError(
            "SALES_ORDER_NOT_FOUND", "Sales order was not found.", kind="not_found"
        )
    order, warehouse = result
    return _sales_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def confirm_sales_order(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
    request: OrderActionRequest,
) -> SalesOrderResponse:
    _require(permissions, "inventory.sale")
    result = repository.get_sales_order(
        session, tenant_id=tenant_id, order_id=order_id, for_update=True
    )
    if result is None:
        raise ApplicationError(
            "SALES_ORDER_NOT_FOUND", "Sales order was not found.", kind="not_found"
        )
    order, warehouse = result
    if order.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Sales order changed; refresh first.", kind="conflict")
    if order.status != "DRAFT":
        raise ApplicationError(
            "SALES_ORDER_STATE_INVALID",
            "Only draft sales orders can be confirmed.",
            kind="conflict",
        )
    item_rows = repository.list_sales_order_items(
        session, tenant_id=tenant_id, order_id=order.id
    )
    balances: dict[UUID, InventoryBalanceRow] = {}
    for item, _sku, _product in sorted(item_rows, key=lambda row: str(row[0].sku_id)):
        balance = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            sku_id=item.sku_id,
        )
        if balance.on_hand_quantity - balance.reserved_quantity < item.quantity:
            raise ApplicationError(
                "INSUFFICIENT_AVAILABLE_STOCK",
                "Available stock is insufficient to confirm this sales order.",
                kind="conflict",
            )
        balances[item.sku_id] = balance
    document = _new_document(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        prefix="RSV",
        document_type="SALES_RESERVATION",
        warehouse_id=warehouse.id,
        source_type="SALES_ORDER",
        source_id=order.id,
        source_number=order.order_number,
        notes="销售单确认，锁定待发库存",
    )
    for line_number, (item, _sku, _product) in enumerate(item_rows, 1):
        document_item = InventoryDocumentItemRow(
            tenant_id=tenant_id,
            document_id=document.id,
            sku_id=item.sku_id,
            sales_order_item_id=item.id,
            line_number=line_number,
            quantity=item.quantity,
            unit_cost=balances[item.sku_id].average_cost,
        )
        session.add(document_item)
        session.flush()
        _apply_movement(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            balance=balances[item.sku_id],
            document=document,
            document_item=document_item,
            movement_type="SALES_RESERVATION",
            on_hand_delta=ZERO,
            reserved_delta=item.quantity,
        )
        item.reserved_quantity = item.quantity
    order.status = "CONFIRMED"
    order.confirmed_at = document.occurred_at
    order.version += 1
    _commit(
        session,
        code="SALES_RESERVATION_CONFLICT",
        message="Stock could not be reserved. Refresh inventory and retry.",
    )
    return _sales_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def ship_sales_order(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
    request: SalesShipmentRequest,
) -> SalesOrderResponse:
    _require(permissions, "inventory.sale")
    duplicate = _idempotent_document(
        session,
        tenant_id=tenant_id,
        idempotency_key=request.idempotency_key,
        document_type="SALES_SHIPMENT",
        source_id=order_id,
    )
    result = repository.get_sales_order(
        session, tenant_id=tenant_id, order_id=order_id, for_update=True
    )
    if result is None:
        raise ApplicationError(
            "SALES_ORDER_NOT_FOUND", "Sales order was not found.", kind="not_found"
        )
    order, warehouse = result
    if duplicate is not None:
        return _sales_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)
    if order.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Sales order changed; refresh first.", kind="conflict")
    if order.status not in {"CONFIRMED", "PARTIALLY_SHIPPED"}:
        raise ApplicationError(
            "SALES_ORDER_STATE_INVALID",
            "Only confirmed sales orders can be shipped.",
            kind="conflict",
        )
    item_rows = repository.list_sales_order_items(
        session, tenant_id=tenant_id, order_id=order.id
    )
    items_by_id = {item.id: item for item, _sku, _product in item_rows}
    for line in request.items:
        item = items_by_id.get(line.order_item_id)
        if item is None:
            raise ApplicationError(
                "SALES_ITEM_NOT_FOUND",
                "A shipment line does not belong to this sales order.",
                kind="not_found",
            )
        if line.quantity > item.reserved_quantity:
            raise ApplicationError(
                "SHIPMENT_EXCEEDS_RESERVED",
                "Shipment quantity exceeds the remaining reserved quantity.",
                kind="conflict",
            )
    document = _new_document(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        prefix="SH",
        document_type="SALES_SHIPMENT",
        warehouse_id=warehouse.id,
        source_type="SALES_ORDER",
        source_id=order.id,
        source_number=order.order_number,
        idempotency_key=request.idempotency_key,
        notes=request.notes.strip() if request.notes else None,
        occurred_at=request.occurred_at,
    )
    for line_number, line in enumerate(request.items, 1):
        item = items_by_id[line.order_item_id]
        balance = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            sku_id=item.sku_id,
        )
        document_item = InventoryDocumentItemRow(
            tenant_id=tenant_id,
            document_id=document.id,
            sku_id=item.sku_id,
            sales_order_item_id=item.id,
            line_number=line_number,
            quantity=_quantity(line.quantity),
            unit_cost=balance.average_cost,
        )
        session.add(document_item)
        session.flush()
        movement = _apply_movement(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            balance=balance,
            document=document,
            document_item=document_item,
            movement_type="SALES_SHIPMENT",
            on_hand_delta=-line.quantity,
            reserved_delta=-line.quantity,
        )
        item.reserved_quantity = _quantity(item.reserved_quantity - line.quantity)
        item.shipped_quantity = _quantity(item.shipped_quantity + line.quantity)
        item.cost_amount = _quantity(item.cost_amount + abs(movement.total_cost))
    all_shipped = all(item.shipped_quantity == item.quantity for item in items_by_id.values())
    order.status = "SHIPPED" if all_shipped else "PARTIALLY_SHIPPED"
    order.completed_at = document.occurred_at if all_shipped else None
    order.version += 1
    _commit(
        session,
        code="SALES_SHIPMENT_CONFLICT",
        message="Shipment could not be posted. Refresh inventory and retry.",
    )
    return _sales_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def cancel_sales_order(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    order_id: UUID,
    request: OrderActionRequest,
) -> SalesOrderResponse:
    _require(permissions, "inventory.sale")
    result = repository.get_sales_order(
        session, tenant_id=tenant_id, order_id=order_id, for_update=True
    )
    if result is None:
        raise ApplicationError(
            "SALES_ORDER_NOT_FOUND", "Sales order was not found.", kind="not_found"
        )
    order, warehouse = result
    if order.version != request.expected_version:
        raise ApplicationError("VERSION_CONFLICT", "Sales order changed; refresh first.", kind="conflict")
    if order.status in {"SHIPPED", "CANCELLED"}:
        raise ApplicationError(
            "SALES_ORDER_STATE_INVALID",
            "Completed or cancelled sales orders cannot be cancelled again.",
            kind="conflict",
        )
    item_rows = repository.list_sales_order_items(
        session, tenant_id=tenant_id, order_id=order.id
    )
    releasable = [row for row in item_rows if row[0].reserved_quantity > 0]
    if releasable:
        document = _new_document(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            prefix="REL",
            document_type="SALES_RELEASE",
            warehouse_id=warehouse.id,
            source_type="SALES_ORDER",
            source_id=order.id,
            source_number=order.order_number,
            notes=request.reason.strip() if request.reason else "销售单取消，释放未发库存",
        )
        for line_number, (item, _sku, _product) in enumerate(releasable, 1):
            balance = _ensure_balance(
                session,
                tenant_id=tenant_id,
                warehouse_id=warehouse.id,
                sku_id=item.sku_id,
            )
            document_item = InventoryDocumentItemRow(
                tenant_id=tenant_id,
                document_id=document.id,
                sku_id=item.sku_id,
                sales_order_item_id=item.id,
                line_number=line_number,
                quantity=item.reserved_quantity,
                unit_cost=balance.average_cost,
            )
            session.add(document_item)
            session.flush()
            _apply_movement(
                session,
                tenant_id=tenant_id,
                membership_id=membership_id,
                balance=balance,
                document=document,
                document_item=document_item,
                movement_type="SALES_RELEASE",
                on_hand_delta=ZERO,
                reserved_delta=-item.reserved_quantity,
            )
            item.reserved_quantity = ZERO
    order.status = "CANCELLED"
    order.completed_at = utcnow()
    if request.reason:
        order.notes = "\n".join(filter(None, [order.notes, f"取消原因：{request.reason.strip()}"]))
    order.version += 1
    session.commit()
    return _sales_response(session, tenant_id=tenant_id, order=order, warehouse=warehouse)


def adjust_inventory(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: InventoryAdjustmentRequest,
) -> InventoryDocumentResponse:
    _require(permissions, "inventory.adjust")
    duplicate = _idempotent_document(
        session,
        tenant_id=tenant_id,
        idempotency_key=request.idempotency_key,
        document_type="MANUAL_ADJUSTMENT",
        source_id=None,
    )
    if duplicate is not None:
        return _document_response(session, tenant_id=tenant_id, document=duplicate)
    warehouse = _active_warehouse(
        session,
        tenant_id=tenant_id,
        warehouse_id=request.warehouse_id,
        membership_id=membership_id,
    )
    sku_ids = {item.sku_id for item in request.items}
    if len(repository.get_skus(session, tenant_id=tenant_id, sku_ids=sku_ids)) != len(sku_ids):
        raise ApplicationError("SKU_NOT_FOUND", "One or more SKUs were not found.", kind="not_found")
    document = _new_document(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        prefix="ADJ",
        document_type="MANUAL_ADJUSTMENT",
        warehouse_id=warehouse.id,
        source_type="MANUAL",
        idempotency_key=request.idempotency_key,
        notes=request.reason.strip(),
        occurred_at=request.occurred_at,
    )
    for line_number, item in enumerate(request.items, 1):
        balance = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=warehouse.id,
            sku_id=item.sku_id,
        )
        document_item = InventoryDocumentItemRow(
            tenant_id=tenant_id,
            document_id=document.id,
            sku_id=item.sku_id,
            line_number=line_number,
            quantity=_quantity(item.quantity_delta),
            unit_cost=item.unit_cost if item.quantity_delta > 0 else balance.average_cost,
        )
        session.add(document_item)
        session.flush()
        _apply_movement(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            balance=balance,
            document=document,
            document_item=document_item,
            movement_type="MANUAL_ADJUSTMENT",
            on_hand_delta=item.quantity_delta,
            reserved_delta=ZERO,
            inbound_unit_cost=item.unit_cost if item.quantity_delta > 0 else None,
        )
    _commit(
        session,
        code="INVENTORY_ADJUSTMENT_CONFLICT",
        message="Inventory adjustment could not be posted. Refresh and retry.",
    )
    return _document_response(session, tenant_id=tenant_id, document=document)


def transfer_stock(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: StockTransferRequest,
) -> InventoryDocumentResponse:
    _require(permissions, "inventory.transfer")
    duplicate = _idempotent_document(
        session,
        tenant_id=tenant_id,
        idempotency_key=request.idempotency_key,
        document_type="STOCK_TRANSFER",
        source_id=None,
    )
    if duplicate is not None:
        return _document_response(session, tenant_id=tenant_id, document=duplicate)
    source = _active_warehouse(
        session, tenant_id=tenant_id, warehouse_id=request.from_warehouse_id
    )
    destination = _active_warehouse(
        session, tenant_id=tenant_id, warehouse_id=request.to_warehouse_id
    )
    if source.currency != destination.currency:
        raise ApplicationError(
            "WAREHOUSE_CURRENCY_MISMATCH",
            "Stock can only be transferred between warehouses using the same valuation currency.",
            kind="conflict",
        )
    sku_ids = {item.sku_id for item in request.items}
    if len(repository.get_skus(session, tenant_id=tenant_id, sku_ids=sku_ids)) != len(sku_ids):
        raise ApplicationError("SKU_NOT_FOUND", "One or more SKUs were not found.", kind="not_found")
    source_balances: dict[UUID, InventoryBalanceRow] = {}
    destination_balances: dict[UUID, InventoryBalanceRow] = {}
    for item in sorted(request.items, key=lambda row: str(row.sku_id)):
        source_balance = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=source.id,
            sku_id=item.sku_id,
        )
        if source_balance.on_hand_quantity - source_balance.reserved_quantity < item.quantity:
            raise ApplicationError(
                "INSUFFICIENT_AVAILABLE_STOCK",
                "Available stock is insufficient for this transfer.",
                kind="conflict",
            )
        source_balances[item.sku_id] = source_balance
        destination_balances[item.sku_id] = _ensure_balance(
            session,
            tenant_id=tenant_id,
            warehouse_id=destination.id,
            sku_id=item.sku_id,
        )
    document = _new_document(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        prefix="TR",
        document_type="STOCK_TRANSFER",
        warehouse_id=source.id,
        counterparty_warehouse_id=destination.id,
        source_type="WAREHOUSE_TRANSFER",
        idempotency_key=request.idempotency_key,
        notes=request.reason.strip(),
        occurred_at=request.occurred_at,
    )
    for line_number, item in enumerate(request.items, 1):
        source_balance = source_balances[item.sku_id]
        transfer_cost = source_balance.average_cost
        document_item = InventoryDocumentItemRow(
            tenant_id=tenant_id,
            document_id=document.id,
            sku_id=item.sku_id,
            line_number=line_number,
            quantity=_quantity(item.quantity),
            unit_cost=transfer_cost,
        )
        session.add(document_item)
        session.flush()
        _apply_movement(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            balance=source_balance,
            document=document,
            document_item=document_item,
            movement_type="TRANSFER_OUT",
            on_hand_delta=-item.quantity,
            reserved_delta=ZERO,
        )
        _apply_movement(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            balance=destination_balances[item.sku_id],
            document=document,
            document_item=document_item,
            movement_type="TRANSFER_IN",
            on_hand_delta=item.quantity,
            reserved_delta=ZERO,
            inbound_unit_cost=transfer_cost,
        )
    _commit(
        session,
        code="STOCK_TRANSFER_CONFLICT",
        message="Stock transfer could not be posted. Refresh and retry.",
    )
    return _document_response(session, tenant_id=tenant_id, document=document)
