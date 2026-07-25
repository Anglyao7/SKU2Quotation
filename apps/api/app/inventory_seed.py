from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .identity_models import TenantRow
from .inventory_models import WarehouseRow
from .model_mixins import restore_deleted


def ensure_default_warehouse(
    session: Session,
    *,
    tenant_id: UUID,
    created_by_membership_id: UUID | None = None,
) -> WarehouseRow:
    """Idempotently provision one active valuation warehouse for a tenant."""

    existing = session.scalar(
        select(WarehouseRow)
        .where(
            WarehouseRow.tenant_id == tenant_id,
            WarehouseRow.is_default.is_(True),
        )
        .execution_options(include_deleted=True)
    )
    if existing is not None:
        if existing.deleted_at is not None:
            restore_deleted(existing)
        existing.status = "ACTIVE"
        return existing

    active = session.scalar(
        select(WarehouseRow)
        .where(
            WarehouseRow.tenant_id == tenant_id,
            WarehouseRow.status == "ACTIVE",
            WarehouseRow.deleted_at.is_(None),
        )
        .order_by(WarehouseRow.created_at)
    )
    if active is not None:
        active.is_default = True
        active.version += 1
        return active

    tenant = session.get(TenantRow, tenant_id)
    currency = (tenant.default_currency if tenant is not None else "CNY").upper()
    warehouse = WarehouseRow(
        tenant_id=tenant_id,
        code="MAIN",
        name="默认仓库",
        currency=currency,
        status="ACTIVE",
        is_default=True,
        created_by_membership_id=created_by_membership_id,
    )
    session.add(warehouse)
    session.flush()
    return warehouse
