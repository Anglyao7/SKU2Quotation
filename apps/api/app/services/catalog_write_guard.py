"""Serialize catalog writes that grant or release batch rollback ownership."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..product_center_models import SkuRow


def lock_catalog_write(session: Session, *, tenant_id: UUID) -> None:
    """Acquire the tenant-scoped catalog write lock for this transaction."""

    tenant_exists = session.scalar(
        select(TenantRow.id)
        .where(TenantRow.id == tenant_id)
        .with_for_update()
    )
    if tenant_exists is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND",
            "Tenant was not found.",
            kind="not_found",
        )


def release_rollback_ownership(
    session: Session,
    *,
    tenant_id: UUID,
    sku_ids: list[UUID] | None = None,
    product_ids: list[UUID] | None = None,
) -> None:
    """Protect later human catalog work from destructive batch rollback."""

    statement = select(SkuRow).where(
        SkuRow.tenant_id == tenant_id,
        SkuRow.rollback_owner_batch_id.is_not(None),
    )
    if sku_ids is not None:
        if not sku_ids:
            return
        statement = statement.where(SkuRow.id.in_(sku_ids))
    if product_ids is not None:
        if not product_ids:
            return
        statement = statement.where(SkuRow.product_id.in_(product_ids))
    rows = session.scalars(statement.with_for_update()).all()
    for row in rows:
        row.rollback_owner_batch_id = None
