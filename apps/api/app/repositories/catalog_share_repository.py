from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..product_center_models import SkuRow
from ..product_supplier_models import ProductCategoryRow, ProductRow
from ..public_catalog_models import CatalogShareRow


def find_by_token(
    session: Session, *, tenant_id: UUID, token: str
) -> CatalogShareRow | None:
    normalized = token.strip()
    identifiers = [CatalogShareRow.share_token == normalized]
    try:
        identifiers.append(CatalogShareRow.id == UUID(normalized))
    except (TypeError, ValueError, AttributeError):
        pass
    return session.scalar(
        select(CatalogShareRow).where(
            CatalogShareRow.tenant_id == tenant_id,
            or_(*identifiers),
            CatalogShareRow.deleted_at.is_(None),
        )
    )


def find_by_fingerprint(
    session: Session, *, tenant_id: UUID, fingerprint: str
) -> CatalogShareRow | None:
    return session.scalar(
        select(CatalogShareRow).where(
            CatalogShareRow.tenant_id == tenant_id,
            CatalogShareRow.fingerprint == fingerprint,
            CatalogShareRow.deleted_at.is_(None),
        )
    )


def list_skus(
    session: Session, *, tenant_id: UUID, sku_ids: list[UUID]
) -> list[SkuRow]:
    if not sku_ids:
        return []
    return list(
        session.scalars(
            select(SkuRow).where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.id.in_(sku_ids),
                SkuRow.deleted_at.is_(None),
            )
        ).all()
    )


def list_products(
    session: Session, *, tenant_id: UUID, product_ids: list[UUID]
) -> list[ProductRow]:
    if not product_ids:
        return []
    return list(
        session.scalars(
            select(ProductRow).where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.id.in_(product_ids),
                ProductRow.deleted_at.is_(None),
            )
        ).all()
    )


def get_category(
    session: Session, *, tenant_id: UUID, category_id: UUID
) -> ProductCategoryRow | None:
    return session.scalar(
        select(ProductCategoryRow).where(
            ProductCategoryRow.tenant_id == tenant_id,
            ProductCategoryRow.id == category_id,
            ProductCategoryRow.deleted_at.is_(None),
        )
    )


def add(session: Session, row: CatalogShareRow) -> CatalogShareRow:
    session.add(row)
    session.flush()
    return row
