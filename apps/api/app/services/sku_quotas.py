from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..identity_models import TenantRow, TenantSubscriptionRow
from ..product_center_models import SkuRow
from ..tenant_subscriptions import default_sku_limit


@dataclass(frozen=True, slots=True)
class SkuQuotaSnapshot:
    current: int
    additional: int
    projected: int
    limit: int | None

    @property
    def exceeded(self) -> bool:
        return self.limit is not None and self.projected > self.limit

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(0, self.limit - self.current)


def sku_quota_message(snapshot: SkuQuotaSnapshot) -> str:
    if snapshot.limit is None:
        return "当前商家 SKU 配额不限。"
    return (
        f"SKU 数量将超过当前等级上限：已使用 {snapshot.current}，"
        f"本次新增 {snapshot.additional}，上限 {snapshot.limit}。"
        "请减少本次新增数量、删除不再使用的 SKU，或联系平台管理员调整配额。"
    )


def sku_quota_snapshot(
    session: Session,
    *,
    tenant_id: UUID,
    additional: int,
    current_count: int | None = None,
    lock_tenant: bool = True,
) -> SkuQuotaSnapshot:
    if additional < 0:
        raise ValueError("additional SKU count cannot be negative")

    if lock_tenant:
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

    subscription = session.scalar(
        select(TenantSubscriptionRow)
        .where(TenantSubscriptionRow.tenant_id == tenant_id)
        .with_for_update()
    )
    limit = (
        subscription.sku_limit
        if subscription is not None
        else default_sku_limit("TRIAL")
    )
    current = (
        int(current_count)
        if current_count is not None
        else int(
            session.scalar(
                select(func.count(SkuRow.id)).where(
                    SkuRow.tenant_id == tenant_id,
                    SkuRow.deleted_at.is_(None),
                )
            )
            or 0
        )
    )
    return SkuQuotaSnapshot(
        current=current,
        additional=additional,
        projected=current + additional,
        limit=limit,
    )


def ensure_sku_capacity(
    session: Session,
    *,
    tenant_id: UUID,
    additional: int,
) -> SkuQuotaSnapshot:
    snapshot = sku_quota_snapshot(
        session,
        tenant_id=tenant_id,
        additional=additional,
        lock_tenant=True,
    )
    if snapshot.exceeded:
        raise ApplicationError(
            "SKU_LIMIT_EXCEEDED",
            sku_quota_message(snapshot),
            kind="conflict",
        )
    return snapshot
