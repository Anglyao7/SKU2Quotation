from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..announcement_models import StorefrontAnnouncementRow
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductRow
from ..public_catalog_models import PublicCatalogOfferRow


@dataclass(frozen=True)
class AnnouncementSkuSummary:
    id: UUID
    product_id: UUID
    sku_code: str
    name: str
    product_name: str
    is_public: bool


def list_for_tenant(
    session: Session,
    *,
    tenant_id: UUID,
) -> tuple[list[StorefrontAnnouncementRow], int]:
    predicate = StorefrontAnnouncementRow.tenant_id == tenant_id
    total = int(
        session.scalar(
            select(func.count(StorefrontAnnouncementRow.id)).where(predicate)
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(StorefrontAnnouncementRow)
            .where(predicate)
            .order_by(
                StorefrontAnnouncementRow.starts_at.desc(),
                StorefrontAnnouncementRow.created_at.desc(),
            )
        ).all()
    )
    return rows, total


def get_for_tenant(
    session: Session,
    *,
    tenant_id: UUID,
    announcement_id: UUID,
) -> StorefrontAnnouncementRow | None:
    return session.scalar(
        select(StorefrontAnnouncementRow).where(
            StorefrontAnnouncementRow.tenant_id == tenant_id,
            StorefrontAnnouncementRow.id == announcement_id,
        )
    )


def list_active(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
) -> list[StorefrontAnnouncementRow]:
    return list(
        session.scalars(
            select(StorefrontAnnouncementRow)
            .where(
                StorefrontAnnouncementRow.tenant_id == tenant_id,
                StorefrontAnnouncementRow.publication_status == "PUBLISHED",
                StorefrontAnnouncementRow.starts_at <= now,
                StorefrontAnnouncementRow.ends_at > now,
            )
            .order_by(
                StorefrontAnnouncementRow.starts_at.desc(),
                StorefrontAnnouncementRow.created_at.desc(),
            )
        ).all()
    )


def list_related_skus(
    session: Session,
    *,
    tenant_id: UUID,
    sku_ids: list[UUID],
    now: datetime,
) -> list[AnnouncementSkuSummary]:
    if not sku_ids:
        return []
    rows = session.execute(
        select(SkuRow, ProductRow, PublicCatalogOfferRow)
        .join(
            ProductRow,
            and_(
                ProductRow.tenant_id == SkuRow.tenant_id,
                ProductRow.id == SkuRow.product_id,
            ),
        )
        .outerjoin(
            PublicCatalogOfferRow,
            and_(
                PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id,
                PublicCatalogOfferRow.sku_id == SkuRow.id,
                PublicCatalogOfferRow.deleted_at.is_(None),
            ),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.id.in_(sku_ids),
            SkuRow.deleted_at.is_(None),
            ProductRow.deleted_at.is_(None),
        )
    ).all()
    by_id: dict[UUID, AnnouncementSkuSummary] = {}
    for sku, product, offer in rows:
        valid_from = offer.valid_from if offer is not None else None
        valid_to = offer.valid_to if offer is not None else None
        if valid_from is not None and valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=UTC)
        if valid_to is not None and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=UTC)
        offer_is_current = bool(
            offer is not None
            and offer.publication_status == "PUBLISHED"
            and (valid_from is None or valid_from <= now)
            and (valid_to is None or valid_to >= now)
        )
        by_id[sku.id] = AnnouncementSkuSummary(
            id=sku.id,
            product_id=product.id,
            sku_code=sku.sku_code,
            name=(sku.name or product.name or sku.sku_code).strip(),
            product_name=product.name,
            is_public=(
                sku.status == "ACTIVE"
                and product.status == "ACTIVE"
                and offer_is_current
            ),
        )
    return [by_id[sku_id] for sku_id in sku_ids if sku_id in by_id]
