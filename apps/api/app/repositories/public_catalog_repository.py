from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, case, cast, func, or_, select
from sqlalchemy.orm import Session

from ..identity_models import TenantRow
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductCategoryRow, ProductImageRow, ProductRow
from ..public_catalog_models import (
    PublicCatalogOfferRow,
    PublicQuoteDownloadTokenRow,
    PublicQuoteDraftItemRow,
    PublicQuoteDraftRow,
    TenantPublicProfileRow,
)


def find_published_profile_by_slug(
    session: Session, *, slug: str
) -> TenantPublicProfileRow | None:
    normalized = slug.casefold().strip()
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.slug == normalized,
            TenantPublicProfileRow.publication_status == "PUBLISHED",
            TenantPublicProfileRow.deleted_at.is_(None),
        )
    )
    if profile is not None:
        return profile
    profiles = session.scalars(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.publication_status == "PUBLISHED",
            TenantPublicProfileRow.deleted_at.is_(None),
        )
    ).all()
    return next(
        (
            row
            for row in profiles
            if normalized
            in {
                str(alias).casefold().strip()
                for alias in (row.legacy_slugs or [])
                if str(alias).strip()
            }
        ),
        None,
    )


def find_published_profile_by_tenant(
    session: Session, *, tenant_id: UUID
) -> TenantPublicProfileRow | None:
    return session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id,
            TenantPublicProfileRow.publication_status == "PUBLISHED",
        )
    )


def find_profile_by_tenant(
    session: Session, *, tenant_id: UUID
) -> TenantPublicProfileRow | None:
    return session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id,
        )
    )


def get_active_tenant(
    session: Session, *, tenant_id: UUID, slug: str | None = None
) -> TenantRow | None:
    statement = select(TenantRow).where(
        TenantRow.id == tenant_id,
        TenantRow.status == "active",
    )
    if slug is not None:
        statement = statement.where(TenantRow.slug == slug)
    return session.scalar(statement)


def list_public_catalog_rows(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
):
    statement = (
        select(PublicCatalogOfferRow, SkuRow, ProductRow, ProductCategoryRow)
        .join(
            SkuRow,
            (SkuRow.tenant_id == PublicCatalogOfferRow.tenant_id)
            & (SkuRow.id == PublicCatalogOfferRow.sku_id),
        )
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .outerjoin(
            ProductCategoryRow,
            (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
            & (ProductCategoryRow.id == ProductRow.category_id),
        )
        .where(
            PublicCatalogOfferRow.tenant_id == tenant_id,
            PublicCatalogOfferRow.publication_status == "PUBLISHED",
            or_(
                PublicCatalogOfferRow.valid_from.is_(None),
                PublicCatalogOfferRow.valid_from <= now,
            ),
            or_(
                PublicCatalogOfferRow.valid_to.is_(None),
                PublicCatalogOfferRow.valid_to >= now,
            ),
            SkuRow.tenant_id == tenant_id,
            SkuRow.status == "ACTIVE",
            ProductRow.tenant_id == tenant_id,
            ProductRow.status == "ACTIVE",
        )
    )
    if category:
        normalized_category = category.casefold().strip()
        category_path = func.lower(
            func.coalesce(ProductCategoryRow.path, ProductCategoryRow.name)
        )
        statement = statement.where(
            or_(
                func.lower(ProductCategoryRow.name) == normalized_category,
                category_path == normalized_category,
                category_path.startswith(
                    f"{normalized_category}/", autoescape=True
                ),
            )
        )
    normalized = query.casefold().strip()
    if normalized:
        statement = statement.where(
            or_(
                func.lower(SkuRow.sku_code).contains(normalized),
                func.lower(func.coalesce(SkuRow.name, "")).contains(normalized),
                func.lower(ProductRow.name).contains(normalized),
                func.lower(func.coalesce(ProductRow.description, "")).contains(normalized),
                func.lower(func.coalesce(ProductCategoryRow.name, "")).contains(normalized),
                func.lower(func.coalesce(ProductCategoryRow.path, "")).contains(normalized),
                func.lower(cast(PublicCatalogOfferRow.tags, Text)).contains(normalized),
            )
        ).order_by(
            case((func.lower(SkuRow.sku_code) == normalized, 0), else_=1),
            ProductRow.name,
            SkuRow.sku_code,
        )
    else:
        statement = statement.order_by(
            ProductCategoryRow.path,
            ProductRow.name,
            SkuRow.sku_code,
        )
    return list(session.execute(statement).all())


def list_catalog_categories(
    session: Session, *, tenant_id: UUID
) -> list[ProductCategoryRow]:
    return list(
        session.scalars(
            select(ProductCategoryRow)
            .where(ProductCategoryRow.tenant_id == tenant_id)
            .order_by(ProductCategoryRow.sort_order, ProductCategoryRow.name)
        ).all()
    )


def list_public_catalog_rows_by_sku_ids(
    session: Session,
    *,
    tenant_id: UUID,
    sku_ids: list[UUID],
    now: datetime,
):
    if not sku_ids:
        return []
    return list(
        session.execute(
            select(PublicCatalogOfferRow, SkuRow, ProductRow, ProductCategoryRow)
            .join(
                SkuRow,
                (SkuRow.tenant_id == PublicCatalogOfferRow.tenant_id)
                & (SkuRow.id == PublicCatalogOfferRow.sku_id),
            )
            .join(
                ProductRow,
                (ProductRow.tenant_id == SkuRow.tenant_id)
                & (ProductRow.id == SkuRow.product_id),
            )
            .outerjoin(
                ProductCategoryRow,
                (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
                & (ProductCategoryRow.id == ProductRow.category_id),
            )
            .where(
                PublicCatalogOfferRow.tenant_id == tenant_id,
                PublicCatalogOfferRow.sku_id.in_(sku_ids),
                PublicCatalogOfferRow.publication_status == "PUBLISHED",
                or_(
                    PublicCatalogOfferRow.valid_from.is_(None),
                    PublicCatalogOfferRow.valid_from <= now,
                ),
                or_(
                    PublicCatalogOfferRow.valid_to.is_(None),
                    PublicCatalogOfferRow.valid_to >= now,
                ),
                SkuRow.tenant_id == tenant_id,
                SkuRow.status == "ACTIVE",
                ProductRow.tenant_id == tenant_id,
                ProductRow.status == "ACTIVE",
            )
        ).all()
    )


def approved_image_map(
    session: Session, *, tenant_id: UUID, product_ids: set[UUID]
) -> dict[UUID, ProductImageRow]:
    if not product_ids:
        return {}
    images = session.scalars(
        select(ProductImageRow)
        .where(
            ProductImageRow.tenant_id == tenant_id,
            ProductImageRow.product_id.in_(product_ids),
            ProductImageRow.approval_status == "APPROVED",
        )
        .order_by(
            ProductImageRow.product_id,
            case((ProductImageRow.image_role == "MAIN", 0), else_=1),
            ProductImageRow.sort_order,
            ProductImageRow.id,
        )
    ).all()
    result: dict[UUID, ProductImageRow] = {}
    for image in images:
        result.setdefault(image.product_id, image)
    return result


def get_approved_public_image(
    session: Session, *, tenant_id: UUID, image_id: UUID
) -> ProductImageRow | None:
    return session.scalar(
        select(ProductImageRow).where(
            ProductImageRow.tenant_id == tenant_id,
            ProductImageRow.id == image_id,
            ProductImageRow.approval_status == "APPROVED",
            ProductImageRow.content_type.like("image/%"),
        )
    )


def add_quote_draft(
    session: Session,
    *,
    draft: PublicQuoteDraftRow,
    items: list[PublicQuoteDraftItemRow],
    token: PublicQuoteDownloadTokenRow,
) -> None:
    session.add(draft)
    session.flush()
    for item in items:
        item.quote_draft_id = draft.id
        session.add(item)
    token.quote_draft_id = draft.id
    session.add(token)
    session.flush()


def get_download_token(
    session: Session,
    *,
    tenant_id: UUID,
    quote_draft_id: UUID,
    token_hash: str,
) -> PublicQuoteDownloadTokenRow | None:
    return session.scalar(
        select(PublicQuoteDownloadTokenRow).where(
            PublicQuoteDownloadTokenRow.tenant_id == tenant_id,
            PublicQuoteDownloadTokenRow.quote_draft_id == quote_draft_id,
            PublicQuoteDownloadTokenRow.token_hash == token_hash,
        )
    )


def get_quote_draft(
    session: Session, *, tenant_id: UUID, quote_draft_id: UUID
) -> PublicQuoteDraftRow | None:
    return session.scalar(
        select(PublicQuoteDraftRow).where(
            PublicQuoteDraftRow.tenant_id == tenant_id,
            PublicQuoteDraftRow.id == quote_draft_id,
        )
    )


def list_quote_drafts(
    session: Session, *, tenant_id: UUID, limit: int
) -> list[PublicQuoteDraftRow]:
    return list(
        session.scalars(
            select(PublicQuoteDraftRow)
            .where(PublicQuoteDraftRow.tenant_id == tenant_id)
            .order_by(PublicQuoteDraftRow.created_at.desc(), PublicQuoteDraftRow.id)
            .limit(limit)
        ).all()
    )


def list_quote_draft_items(
    session: Session, *, tenant_id: UUID, quote_draft_id: UUID
) -> list[PublicQuoteDraftItemRow]:
    return list(
        session.scalars(
            select(PublicQuoteDraftItemRow)
            .where(
                PublicQuoteDraftItemRow.tenant_id == tenant_id,
                PublicQuoteDraftItemRow.quote_draft_id == quote_draft_id,
            )
            .order_by(PublicQuoteDraftItemRow.position)
        ).all()
    )
