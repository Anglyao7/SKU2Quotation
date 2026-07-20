from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..identity_models import TenantRow
from ..product_center_models import SkuRow
from ..public_catalog_models import PublicQuoteDraftRow, TenantPublicProfileRow


def list_tenants(session: Session) -> list[TenantRow]:
    return list(session.scalars(select(TenantRow).order_by(TenantRow.created_at, TenantRow.id)).all())


def get_tenant(session: Session, tenant_id: UUID) -> TenantRow | None:
    return session.get(TenantRow, tenant_id)


def find_tenant_by_slug(session: Session, slug: str) -> TenantRow | None:
    return session.scalar(select(TenantRow).where(TenantRow.slug == slug))


def get_public_profile(session: Session, tenant_id: UUID) -> TenantPublicProfileRow | None:
    return session.get(TenantPublicProfileRow, tenant_id)


def tenant_counts(session: Session, tenant_id: UUID) -> tuple[int, int]:
    sku_count = session.scalar(
        select(func.count(SkuRow.id)).where(SkuRow.tenant_id == tenant_id)
    )
    quote_count = session.scalar(
        select(func.count(PublicQuoteDraftRow.id)).where(PublicQuoteDraftRow.tenant_id == tenant_id)
    )
    return int(sku_count or 0), int(quote_count or 0)
