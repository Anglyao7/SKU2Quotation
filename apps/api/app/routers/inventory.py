from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..inventory_schemas import (
    InventoryAdjustmentRequest,
    InventoryDocumentResponse,
    InventoryMovementPage,
    InventoryOverviewResponse,
    InventoryStockItem,
    InventoryStockPage,
    OrderActionRequest,
    PurchaseOrderCreateRequest,
    PurchaseOrderResponse,
    PurchaseOrderSummary,
    PurchaseReceiptRequest,
    SalesOrderCreateRequest,
    SalesOrderResponse,
    SalesOrderSummary,
    SalesShipmentRequest,
    StockPolicyUpdateRequest,
    StockTransferRequest,
    WarehouseCreateRequest,
    WarehouseResponse,
    WarehouseUpdateRequest,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import inventory as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["inventory"])


def _context(session: Session):
    return current_context(session)


@router.get("/inventory/warehouses", response_model=list[WarehouseResponse])
def list_warehouses(
    session: Session = Depends(get_authenticated_session),
) -> list[WarehouseResponse]:
    context = _context(session)
    try:
        return use_cases.list_warehouses(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/inventory/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_warehouse(
    request: WarehouseCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> WarehouseResponse:
    context = _context(session)
    try:
        return use_cases.create_warehouse(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/inventory/warehouses/{warehouse_id}", response_model=WarehouseResponse
)
def update_warehouse(
    warehouse_id: UUID,
    request: WarehouseUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> WarehouseResponse:
    context = _context(session)
    try:
        return use_cases.update_warehouse(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            warehouse_id=warehouse_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/inventory/overview", response_model=InventoryOverviewResponse)
def inventory_overview(
    warehouse_id: UUID | None = None,
    session: Session = Depends(get_authenticated_session),
) -> InventoryOverviewResponse:
    context = _context(session)
    try:
        return use_cases.inventory_overview(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            warehouse_id=warehouse_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/inventory/stocks", response_model=InventoryStockPage)
def list_stock(
    warehouse_id: UUID | None = None,
    q: str = Query(default="", max_length=200),
    low_stock_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_authenticated_session),
) -> InventoryStockPage:
    context = _context(session)
    try:
        return use_cases.list_stock(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            warehouse_id=warehouse_id,
            query=q,
            low_stock_only=low_stock_only,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/inventory/stocks/{warehouse_id}/{sku_id}/policy",
    response_model=InventoryStockItem,
)
def update_stock_policy(
    warehouse_id: UUID,
    sku_id: UUID,
    request: StockPolicyUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> InventoryStockItem:
    context = _context(session)
    try:
        return use_cases.update_stock_policy(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/inventory/movements", response_model=InventoryMovementPage)
def list_movements(
    warehouse_id: UUID | None = None,
    q: str = Query(default="", max_length=200),
    movement_type: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_authenticated_session),
) -> InventoryMovementPage:
    context = _context(session)
    try:
        return use_cases.list_movements(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            warehouse_id=warehouse_id,
            query=q,
            movement_type=movement_type,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/inventory/adjustments",
    response_model=InventoryDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def adjust_inventory(
    request: InventoryAdjustmentRequest,
    session: Session = Depends(get_authenticated_session),
) -> InventoryDocumentResponse:
    context = _context(session)
    try:
        return use_cases.adjust_inventory(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/inventory/transfers",
    response_model=InventoryDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def transfer_stock(
    request: StockTransferRequest,
    session: Session = Depends(get_authenticated_session),
) -> InventoryDocumentResponse:
    context = _context(session)
    try:
        return use_cases.transfer_stock(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/purchases", response_model=list[PurchaseOrderSummary])
def list_purchase_orders(
    order_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_authenticated_session),
) -> list[PurchaseOrderSummary]:
    context = _context(session)
    try:
        return use_cases.list_purchase_orders(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            status=order_status,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/purchases",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_purchase_order(
    request: PurchaseOrderCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> PurchaseOrderResponse:
    context = _context(session)
    try:
        return use_cases.create_purchase_order(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/purchases/{order_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(
    order_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> PurchaseOrderResponse:
    context = _context(session)
    try:
        return use_cases.get_purchase_order(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            order_id=order_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/purchases/{order_id}/confirm", response_model=PurchaseOrderResponse)
def confirm_purchase_order(
    order_id: UUID,
    request: OrderActionRequest,
    session: Session = Depends(get_authenticated_session),
) -> PurchaseOrderResponse:
    context = _context(session)
    try:
        return use_cases.confirm_purchase_order(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            order_id=order_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/purchases/{order_id}/receive", response_model=PurchaseOrderResponse)
def receive_purchase_order(
    order_id: UUID,
    request: PurchaseReceiptRequest,
    session: Session = Depends(get_authenticated_session),
) -> PurchaseOrderResponse:
    context = _context(session)
    try:
        return use_cases.receive_purchase_order(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            order_id=order_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/purchases/{order_id}/cancel", response_model=PurchaseOrderResponse)
def cancel_purchase_order(
    order_id: UUID,
    request: OrderActionRequest,
    session: Session = Depends(get_authenticated_session),
) -> PurchaseOrderResponse:
    context = _context(session)
    try:
        return use_cases.cancel_purchase_order(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            order_id=order_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/sales-orders", response_model=list[SalesOrderSummary])
def list_sales_orders(
    order_status: str | None = Query(default=None, alias="status", max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_authenticated_session),
) -> list[SalesOrderSummary]:
    context = _context(session)
    try:
        return use_cases.list_sales_orders(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            status=order_status,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/sales-orders",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_sales_order(
    request: SalesOrderCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> SalesOrderResponse:
    context = _context(session)
    try:
        return use_cases.create_sales_order(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/sales-orders/{order_id}", response_model=SalesOrderResponse)
def get_sales_order(
    order_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> SalesOrderResponse:
    context = _context(session)
    try:
        return use_cases.get_sales_order(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            order_id=order_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/sales-orders/{order_id}/confirm", response_model=SalesOrderResponse)
def confirm_sales_order(
    order_id: UUID,
    request: OrderActionRequest,
    session: Session = Depends(get_authenticated_session),
) -> SalesOrderResponse:
    context = _context(session)
    try:
        return use_cases.confirm_sales_order(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            order_id=order_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/sales-orders/{order_id}/ship", response_model=SalesOrderResponse)
def ship_sales_order(
    order_id: UUID,
    request: SalesShipmentRequest,
    session: Session = Depends(get_authenticated_session),
) -> SalesOrderResponse:
    context = _context(session)
    try:
        return use_cases.ship_sales_order(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            order_id=order_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/sales-orders/{order_id}/cancel", response_model=SalesOrderResponse)
def cancel_sales_order(
    order_id: UUID,
    request: OrderActionRequest,
    session: Session = Depends(get_authenticated_session),
) -> SalesOrderResponse:
    context = _context(session)
    try:
        return use_cases.cancel_sales_order(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            order_id=order_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
