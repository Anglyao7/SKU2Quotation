from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..db_models import SupplierRow
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
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductRow
from ..trade_flow_models import CustomerRow, QuotationRow


@dataclass(frozen=True)
class StockQueryRow:
    sku: SkuRow
    product: ProductRow
    supplier: SupplierRow | None
    balance: InventoryBalanceRow | None


@dataclass(frozen=True)
class MovementQueryRow:
    movement: InventoryMovementRow
    document: InventoryDocumentRow
    warehouse: WarehouseRow
    sku: SkuRow
    product: ProductRow


def list_warehouses(session: Session, *, tenant_id: UUID) -> list[WarehouseRow]:
    return session.scalars(
        select(WarehouseRow)
        .where(WarehouseRow.tenant_id == tenant_id, WarehouseRow.deleted_at.is_(None))
        .order_by(WarehouseRow.is_default.desc(), WarehouseRow.name, WarehouseRow.code)
    ).all()


def get_warehouse(
    session: Session, *, tenant_id: UUID, warehouse_id: UUID
) -> WarehouseRow | None:
    return session.scalar(
        select(WarehouseRow).where(
            WarehouseRow.tenant_id == tenant_id,
            WarehouseRow.id == warehouse_id,
            WarehouseRow.deleted_at.is_(None),
        )
    )


def get_warehouse_for_update(
    session: Session, *, tenant_id: UUID, warehouse_id: UUID
) -> WarehouseRow | None:
    return session.scalar(
        select(WarehouseRow)
        .where(
            WarehouseRow.tenant_id == tenant_id,
            WarehouseRow.id == warehouse_id,
            WarehouseRow.deleted_at.is_(None),
        )
        .with_for_update()
    )


def get_default_warehouse(session: Session, *, tenant_id: UUID) -> WarehouseRow | None:
    return session.scalar(
        select(WarehouseRow).where(
            WarehouseRow.tenant_id == tenant_id,
            WarehouseRow.is_default.is_(True),
            WarehouseRow.status == "ACTIVE",
            WarehouseRow.deleted_at.is_(None),
        )
    )


def clear_default_warehouse(
    session: Session, *, tenant_id: UUID, except_id: UUID | None = None
) -> None:
    statement = update(WarehouseRow).where(
        WarehouseRow.tenant_id == tenant_id,
        WarehouseRow.is_default.is_(True),
        WarehouseRow.deleted_at.is_(None),
    )
    if except_id is not None:
        statement = statement.where(WarehouseRow.id != except_id)
    session.execute(statement.values(is_default=False))


def warehouse_has_stock_or_reservations(
    session: Session, *, tenant_id: UUID, warehouse_id: UUID
) -> bool:
    return bool(
        session.scalar(
            select(func.count(InventoryBalanceRow.id)).where(
                InventoryBalanceRow.tenant_id == tenant_id,
                InventoryBalanceRow.warehouse_id == warehouse_id,
                or_(
                    InventoryBalanceRow.on_hand_quantity > 0,
                    InventoryBalanceRow.reserved_quantity > 0,
                ),
                InventoryBalanceRow.deleted_at.is_(None),
            )
        )
    )


def get_skus(
    session: Session, *, tenant_id: UUID, sku_ids: set[UUID]
) -> dict[UUID, tuple[SkuRow, ProductRow]]:
    if not sku_ids:
        return {}
    rows = session.execute(
        select(SkuRow, ProductRow)
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.id.in_(sku_ids),
            SkuRow.deleted_at.is_(None),
            ProductRow.deleted_at.is_(None),
        )
    ).all()
    return {sku.id: (sku, product) for sku, product in rows}


def get_supplier(
    session: Session, *, tenant_id: UUID, supplier_id: str | None
) -> SupplierRow | None:
    if supplier_id is None:
        return None
    return session.scalar(
        select(SupplierRow).where(
            SupplierRow.tenant_id == tenant_id,
            SupplierRow.id == supplier_id,
            SupplierRow.deleted_at.is_(None),
        )
    )


def get_customer(
    session: Session, *, tenant_id: UUID, customer_id: UUID
) -> CustomerRow | None:
    return session.scalar(
        select(CustomerRow).where(
            CustomerRow.tenant_id == tenant_id,
            CustomerRow.id == customer_id,
            CustomerRow.deleted_at.is_(None),
        )
    )


def get_quotation(
    session: Session, *, tenant_id: UUID, quotation_id: UUID
) -> QuotationRow | None:
    return session.scalar(
        select(QuotationRow).where(
            QuotationRow.tenant_id == tenant_id,
            QuotationRow.id == quotation_id,
            QuotationRow.deleted_at.is_(None),
        )
    )


def get_balance(
    session: Session, *, tenant_id: UUID, warehouse_id: UUID, sku_id: UUID
) -> InventoryBalanceRow | None:
    return session.scalar(
        select(InventoryBalanceRow).where(
            InventoryBalanceRow.tenant_id == tenant_id,
            InventoryBalanceRow.warehouse_id == warehouse_id,
            InventoryBalanceRow.sku_id == sku_id,
            InventoryBalanceRow.deleted_at.is_(None),
        )
    )


def get_balance_for_update(
    session: Session, *, tenant_id: UUID, warehouse_id: UUID, sku_id: UUID
) -> InventoryBalanceRow | None:
    return session.scalar(
        select(InventoryBalanceRow)
        .where(
            InventoryBalanceRow.tenant_id == tenant_id,
            InventoryBalanceRow.warehouse_id == warehouse_id,
            InventoryBalanceRow.sku_id == sku_id,
            InventoryBalanceRow.deleted_at.is_(None),
        )
        .with_for_update()
    )


def list_stock_rows(
    session: Session,
    *,
    tenant_id: UUID,
    warehouse_id: UUID,
    query: str,
    low_stock_only: bool,
    page: int,
    page_size: int,
) -> tuple[list[StockQueryRow], int]:
    balance_join = (
        (InventoryBalanceRow.tenant_id == SkuRow.tenant_id)
        & (InventoryBalanceRow.sku_id == SkuRow.id)
        & (InventoryBalanceRow.warehouse_id == warehouse_id)
        & InventoryBalanceRow.deleted_at.is_(None)
    )
    supplier_join = (
        (SupplierRow.tenant_id == SkuRow.tenant_id)
        & (SupplierRow.id == SkuRow.supplier_id)
        & SupplierRow.deleted_at.is_(None)
    )
    conditions = [
        SkuRow.tenant_id == tenant_id,
        SkuRow.status != "ARCHIVED",
        SkuRow.deleted_at.is_(None),
        ProductRow.deleted_at.is_(None),
    ]
    normalized = query.strip().casefold()
    if normalized:
        conditions.append(
            or_(
                func.lower(SkuRow.sku_code).contains(normalized),
                func.lower(func.coalesce(SkuRow.source_sku_code, "")).contains(
                    normalized
                ),
                func.lower(func.coalesce(SkuRow.name, "")).contains(normalized),
                func.lower(ProductRow.name).contains(normalized),
                func.lower(func.coalesce(ProductRow.product_code, "")).contains(normalized),
                func.lower(func.coalesce(SupplierRow.name, "")).contains(normalized),
            )
        )
    reorder_point = func.coalesce(InventoryBalanceRow.reorder_point, 0)
    available = func.coalesce(InventoryBalanceRow.on_hand_quantity, 0) - func.coalesce(
        InventoryBalanceRow.reserved_quantity, 0
    )
    if low_stock_only:
        conditions.extend((reorder_point > 0, available <= reorder_point))

    base = (
        select(SkuRow, ProductRow, SupplierRow, InventoryBalanceRow)
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .outerjoin(SupplierRow, supplier_join)
        .outerjoin(InventoryBalanceRow, balance_join)
        .where(*conditions)
    )
    count_statement = (
        select(func.count(SkuRow.id))
        .select_from(SkuRow)
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .outerjoin(SupplierRow, supplier_join)
        .outerjoin(InventoryBalanceRow, balance_join)
        .where(*conditions)
    )
    total = int(session.scalar(count_statement) or 0)
    rows = session.execute(
        base.order_by(
            (available <= reorder_point).desc(),
            ProductRow.name,
            SkuRow.sku_code,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        StockQueryRow(
            sku=sku,
            product=product,
            supplier=supplier,
            balance=balance,
        )
        for sku, product, supplier, balance in rows
    ], total


def inventory_aggregates(
    session: Session, *, tenant_id: UUID, warehouse_id: UUID
) -> dict[str, int | object]:
    total_skus = int(
        session.scalar(
            select(func.count(SkuRow.id)).where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.status != "ARCHIVED",
                SkuRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    stock = session.execute(
        select(
            func.count(InventoryBalanceRow.id).filter(
                InventoryBalanceRow.on_hand_quantity > 0
            ),
            func.coalesce(func.sum(InventoryBalanceRow.on_hand_quantity), 0),
            func.coalesce(func.sum(InventoryBalanceRow.reserved_quantity), 0),
            func.coalesce(
                func.sum(
                    InventoryBalanceRow.on_hand_quantity
                    * InventoryBalanceRow.average_cost
                ),
                0,
            ),
            func.count(InventoryBalanceRow.id).filter(
                (InventoryBalanceRow.reorder_point > 0)
                & (
                    InventoryBalanceRow.on_hand_quantity
                    - InventoryBalanceRow.reserved_quantity
                    <= InventoryBalanceRow.reorder_point
                )
            ),
        ).where(
            InventoryBalanceRow.tenant_id == tenant_id,
            InventoryBalanceRow.warehouse_id == warehouse_id,
            InventoryBalanceRow.deleted_at.is_(None),
        )
    ).one()
    open_purchase_orders = int(
        session.scalar(
            select(func.count(PurchaseOrderRow.id)).where(
                PurchaseOrderRow.tenant_id == tenant_id,
                PurchaseOrderRow.warehouse_id == warehouse_id,
                PurchaseOrderRow.status.in_(
                    ("DRAFT", "CONFIRMED", "PARTIALLY_RECEIVED")
                ),
                PurchaseOrderRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    open_sales_orders = int(
        session.scalar(
            select(func.count(SalesOrderRow.id)).where(
                SalesOrderRow.tenant_id == tenant_id,
                SalesOrderRow.warehouse_id == warehouse_id,
                SalesOrderRow.status.in_(("DRAFT", "CONFIRMED", "PARTIALLY_SHIPPED")),
                SalesOrderRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    return {
        "total_skus": total_skus,
        "stocked_skus": int(stock[0] or 0),
        "on_hand_quantity": stock[1],
        "reserved_quantity": stock[2],
        "inventory_value": stock[3],
        "low_stock_count": int(stock[4] or 0),
        "open_purchase_orders": open_purchase_orders,
        "open_sales_orders": open_sales_orders,
    }


def get_document_by_idempotency(
    session: Session, *, tenant_id: UUID, idempotency_key: str
) -> InventoryDocumentRow | None:
    return session.scalar(
        select(InventoryDocumentRow).where(
            InventoryDocumentRow.tenant_id == tenant_id,
            InventoryDocumentRow.idempotency_key == idempotency_key,
            InventoryDocumentRow.deleted_at.is_(None),
        )
    )


def list_document_items(
    session: Session, *, tenant_id: UUID, document_id: UUID
) -> list[tuple[InventoryDocumentItemRow, SkuRow, ProductRow]]:
    return list(
        session.execute(
            select(InventoryDocumentItemRow, SkuRow, ProductRow)
            .join(
                SkuRow,
                (SkuRow.tenant_id == InventoryDocumentItemRow.tenant_id)
                & (SkuRow.id == InventoryDocumentItemRow.sku_id),
            )
            .join(
                ProductRow,
                (ProductRow.tenant_id == SkuRow.tenant_id)
                & (ProductRow.id == SkuRow.product_id),
            )
            .where(
                InventoryDocumentItemRow.tenant_id == tenant_id,
                InventoryDocumentItemRow.document_id == document_id,
                InventoryDocumentItemRow.deleted_at.is_(None),
            )
            .order_by(InventoryDocumentItemRow.line_number)
        ).all()
    )


def list_movements(
    session: Session,
    *,
    tenant_id: UUID,
    warehouse_id: UUID | None,
    query: str,
    movement_type: str | None,
    page: int,
    page_size: int,
) -> tuple[list[MovementQueryRow], int]:
    conditions = [
        InventoryMovementRow.tenant_id == tenant_id,
        InventoryMovementRow.deleted_at.is_(None),
    ]
    if warehouse_id is not None:
        conditions.append(InventoryMovementRow.warehouse_id == warehouse_id)
    if movement_type:
        conditions.append(InventoryMovementRow.movement_type == movement_type)
    normalized = query.strip().casefold()
    if normalized:
        conditions.append(
            or_(
                func.lower(SkuRow.sku_code).contains(normalized),
                func.lower(func.coalesce(SkuRow.source_sku_code, "")).contains(
                    normalized
                ),
                func.lower(func.coalesce(SkuRow.name, "")).contains(normalized),
                func.lower(ProductRow.name).contains(normalized),
                func.lower(InventoryDocumentRow.document_number).contains(normalized),
                func.lower(func.coalesce(InventoryDocumentRow.source_number, "")).contains(
                    normalized
                ),
            )
        )
    statement = (
        select(
            InventoryMovementRow,
            InventoryDocumentRow,
            WarehouseRow,
            SkuRow,
            ProductRow,
        )
        .join(
            InventoryDocumentRow,
            (InventoryDocumentRow.tenant_id == InventoryMovementRow.tenant_id)
            & (InventoryDocumentRow.id == InventoryMovementRow.document_id),
        )
        .join(
            WarehouseRow,
            (WarehouseRow.tenant_id == InventoryMovementRow.tenant_id)
            & (WarehouseRow.id == InventoryMovementRow.warehouse_id),
        )
        .join(
            SkuRow,
            (SkuRow.tenant_id == InventoryMovementRow.tenant_id)
            & (SkuRow.id == InventoryMovementRow.sku_id),
        )
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .where(*conditions)
    )
    total = int(
        session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    )
    rows = session.execute(
        statement.order_by(
            InventoryMovementRow.occurred_at.desc(), InventoryMovementRow.created_at.desc()
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        MovementQueryRow(
            movement=movement,
            document=document,
            warehouse=warehouse,
            sku=sku,
            product=product,
        )
        for movement, document, warehouse, sku, product in rows
    ], total


def list_purchase_orders(
    session: Session, *, tenant_id: UUID, status: str | None, limit: int
) -> list[tuple[PurchaseOrderRow, WarehouseRow]]:
    statement = (
        select(PurchaseOrderRow, WarehouseRow)
        .join(
            WarehouseRow,
            (WarehouseRow.tenant_id == PurchaseOrderRow.tenant_id)
            & (WarehouseRow.id == PurchaseOrderRow.warehouse_id),
        )
        .where(
            PurchaseOrderRow.tenant_id == tenant_id,
            PurchaseOrderRow.deleted_at.is_(None),
        )
    )
    if status:
        statement = statement.where(PurchaseOrderRow.status == status)
    return list(
        session.execute(
            statement.order_by(PurchaseOrderRow.updated_at.desc()).limit(limit)
        ).all()
    )


def get_purchase_order(
    session: Session, *, tenant_id: UUID, order_id: UUID, for_update: bool = False
) -> tuple[PurchaseOrderRow, WarehouseRow] | None:
    statement = (
        select(PurchaseOrderRow, WarehouseRow)
        .join(
            WarehouseRow,
            (WarehouseRow.tenant_id == PurchaseOrderRow.tenant_id)
            & (WarehouseRow.id == PurchaseOrderRow.warehouse_id),
        )
        .where(
            PurchaseOrderRow.tenant_id == tenant_id,
            PurchaseOrderRow.id == order_id,
            PurchaseOrderRow.deleted_at.is_(None),
        )
    )
    if for_update:
        statement = statement.with_for_update(of=PurchaseOrderRow)
    return session.execute(statement).one_or_none()


def list_purchase_order_items(
    session: Session, *, tenant_id: UUID, order_id: UUID
) -> list[tuple[PurchaseOrderItemRow, SkuRow, ProductRow]]:
    return list(
        session.execute(
            select(PurchaseOrderItemRow, SkuRow, ProductRow)
            .join(
                SkuRow,
                (SkuRow.tenant_id == PurchaseOrderItemRow.tenant_id)
                & (SkuRow.id == PurchaseOrderItemRow.sku_id),
            )
            .join(
                ProductRow,
                (ProductRow.tenant_id == SkuRow.tenant_id)
                & (ProductRow.id == SkuRow.product_id),
            )
            .where(
                PurchaseOrderItemRow.tenant_id == tenant_id,
                PurchaseOrderItemRow.purchase_order_id == order_id,
                PurchaseOrderItemRow.deleted_at.is_(None),
            )
            .order_by(PurchaseOrderItemRow.line_number)
        ).all()
    )


def list_sales_orders(
    session: Session, *, tenant_id: UUID, status: str | None, limit: int
) -> list[tuple[SalesOrderRow, WarehouseRow]]:
    statement = (
        select(SalesOrderRow, WarehouseRow)
        .join(
            WarehouseRow,
            (WarehouseRow.tenant_id == SalesOrderRow.tenant_id)
            & (WarehouseRow.id == SalesOrderRow.warehouse_id),
        )
        .where(
            SalesOrderRow.tenant_id == tenant_id,
            SalesOrderRow.deleted_at.is_(None),
        )
    )
    if status:
        statement = statement.where(SalesOrderRow.status == status)
    return list(
        session.execute(statement.order_by(SalesOrderRow.updated_at.desc()).limit(limit)).all()
    )


def get_sales_order(
    session: Session, *, tenant_id: UUID, order_id: UUID, for_update: bool = False
) -> tuple[SalesOrderRow, WarehouseRow] | None:
    statement = (
        select(SalesOrderRow, WarehouseRow)
        .join(
            WarehouseRow,
            (WarehouseRow.tenant_id == SalesOrderRow.tenant_id)
            & (WarehouseRow.id == SalesOrderRow.warehouse_id),
        )
        .where(
            SalesOrderRow.tenant_id == tenant_id,
            SalesOrderRow.id == order_id,
            SalesOrderRow.deleted_at.is_(None),
        )
    )
    if for_update:
        statement = statement.with_for_update(of=SalesOrderRow)
    return session.execute(statement).one_or_none()


def list_sales_order_items(
    session: Session, *, tenant_id: UUID, order_id: UUID
) -> list[tuple[SalesOrderItemRow, SkuRow, ProductRow]]:
    return list(
        session.execute(
            select(SalesOrderItemRow, SkuRow, ProductRow)
            .join(
                SkuRow,
                (SkuRow.tenant_id == SalesOrderItemRow.tenant_id)
                & (SkuRow.id == SalesOrderItemRow.sku_id),
            )
            .join(
                ProductRow,
                (ProductRow.tenant_id == SkuRow.tenant_id)
                & (ProductRow.id == SkuRow.product_id),
            )
            .where(
                SalesOrderItemRow.tenant_id == tenant_id,
                SalesOrderItemRow.sales_order_id == order_id,
                SalesOrderItemRow.deleted_at.is_(None),
            )
            .order_by(SalesOrderItemRow.line_number)
        ).all()
    )
