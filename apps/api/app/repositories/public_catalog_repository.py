from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, case, cast, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

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

ParentProductCategoryRow = aliased(
    ProductCategoryRow,
    name="parent_product_category",
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


def occupied_storefront_slugs(
    session: Session,
    *,
    exclude_tenant_id: UUID | None = None,
) -> set[str]:
    """Return current and legacy storefront paths that cannot be reassigned."""

    tenant_statement = select(TenantRow.slug)
    profile_statement = select(
        TenantPublicProfileRow.slug,
        TenantPublicProfileRow.legacy_slugs,
    ).where(TenantPublicProfileRow.deleted_at.is_(None))
    if exclude_tenant_id is not None:
        tenant_statement = tenant_statement.where(TenantRow.id != exclude_tenant_id)
        profile_statement = profile_statement.where(
            TenantPublicProfileRow.tenant_id != exclude_tenant_id
        )
    occupied = {
        str(slug).casefold().strip()
        for slug in session.scalars(tenant_statement).all()
        if str(slug).strip()
    }
    for slug, legacy_slugs in session.execute(profile_statement).all():
        occupied.update(
            str(value).casefold().strip()
            for value in [slug, *(legacy_slugs or [])]
            if str(value).strip()
        )
    return occupied


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


def _public_catalog_statement(
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
        .outerjoin(
            ParentProductCategoryRow,
            (ParentProductCategoryRow.tenant_id == ProductCategoryRow.tenant_id)
            & (ParentProductCategoryRow.id == ProductCategoryRow.parent_id),
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
        )
    return statement


def _with_catalog_tag_filters(
    session: Session,
    statement,
    *,
    tags: set[str],
):
    """Apply exact, case-insensitive JSON-array tag filters in both supported DBs."""

    dialect = session.get_bind().dialect.name
    for index, tag in enumerate(sorted(tags)):
        if dialect == "postgresql":
            tag_values = func.jsonb_array_elements_text(
                PublicCatalogOfferRow.tags
            ).table_valued("value").alias(f"catalog_tag_{index}")
        else:
            tag_values = func.json_each(
                PublicCatalogOfferRow.tags
            ).table_valued("key", "value").alias(f"catalog_tag_{index}")
        statement = statement.where(
            exists(
                select(1)
                .select_from(tag_values)
                .where(func.lower(cast(tag_values.c.value, Text)) == tag)
            )
        )
    return statement


def _ordered_public_catalog_statement(statement, *, query: str):
    normalized = query.casefold().strip()
    if normalized:
        return statement.order_by(
            case((func.lower(SkuRow.sku_code) == normalized, 0), else_=1),
            ProductRow.name,
            SkuRow.sku_code,
            SkuRow.id,
        )
    return statement.order_by(
        # The category tree is also the storefront merchandising order.
        # Products without a category remain visible, but always come last.
        case((ProductCategoryRow.id.is_(None), 1), else_=0),
        func.coalesce(
            ParentProductCategoryRow.sort_order,
            ProductCategoryRow.sort_order,
            2_147_483_647,
        ),
        func.lower(
            func.coalesce(
                ParentProductCategoryRow.name,
                ProductCategoryRow.name,
                "",
            )
        ),
        # Products assigned directly to the primary category precede its
        # ordered secondary-category groups.
        case(
            (ProductCategoryRow.id.is_(None), 2_147_483_647),
            (ProductCategoryRow.parent_id.is_(None), -1),
            else_=ProductCategoryRow.sort_order,
        ),
        func.lower(func.coalesce(ProductCategoryRow.name, "")),
        ProductRow.name,
        SkuRow.sku_code,
        SkuRow.id,
    )


def list_public_catalog_lexical_candidates(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    terms: list[str],
    category: str | None,
    limit: int,
):
    """Return a bounded OR-match corpus for degraded semantic search."""

    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=category,
    )
    searchable_fields = (
        func.lower(SkuRow.sku_code),
        func.lower(func.coalesce(SkuRow.name, "")),
        func.lower(ProductRow.name),
        func.lower(func.coalesce(ProductRow.description, "")),
        func.lower(func.coalesce(ProductCategoryRow.name, "")),
        func.lower(func.coalesce(ProductCategoryRow.path, "")),
        func.lower(cast(PublicCatalogOfferRow.tags, Text)),
    )
    matches = [
        field.contains(term)
        for term in terms
        if term
        for field in searchable_fields
    ]
    if not matches:
        return []
    statement = statement.where(or_(*matches))
    statement = _ordered_public_catalog_statement(statement, query=query)
    return list(session.execute(statement.limit(limit)).all())


def list_public_catalog_page(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
    tags: set[str],
    page: int,
    page_size: int,
):
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = _with_catalog_tag_filters(session, statement, tags=tags)
    statement = _ordered_public_catalog_statement(statement, query=query)
    return list(
        session.execute(
            statement.offset((page - 1) * page_size).limit(page_size)
        ).all()
    )


def _public_product_id_statement(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
    tags: set[str],
):
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = _with_catalog_tag_filters(session, statement, tags=tags)
    uncategorized = case((ProductCategoryRow.id.is_(None), 1), else_=0)
    root_sort = func.coalesce(
        ParentProductCategoryRow.sort_order,
        ProductCategoryRow.sort_order,
        2_147_483_647,
    )
    root_name = func.lower(
        func.coalesce(
            ParentProductCategoryRow.name,
            ProductCategoryRow.name,
            "",
        )
    )
    child_sort = case(
        (ProductCategoryRow.id.is_(None), 2_147_483_647),
        (ProductCategoryRow.parent_id.is_(None), -1),
        else_=ProductCategoryRow.sort_order,
    )
    child_name = func.lower(func.coalesce(ProductCategoryRow.name, ""))
    product_name = func.lower(ProductRow.name)
    normalized = query.casefold().strip()
    match_rank = func.min(
        case(
            (func.lower(SkuRow.sku_code) == normalized, 0),
            (func.lower(ProductRow.name) == normalized, 1),
            else_=2,
        )
    )
    grouped = (
        statement.with_only_columns(
            ProductRow.id.label("product_id"),
            uncategorized.label("uncategorized"),
            root_sort.label("root_sort"),
            root_name.label("root_name"),
            child_sort.label("child_sort"),
            child_name.label("child_name"),
            product_name.label("product_name"),
            match_rank.label("match_rank"),
        )
        .order_by(None)
        .group_by(
            ProductRow.id,
            uncategorized,
            root_sort,
            root_name,
            child_sort,
            child_name,
            product_name,
        )
    )
    return grouped.order_by(
        match_rank if normalized else uncategorized,
        uncategorized,
        root_sort,
        root_name,
        child_sort,
        child_name,
        product_name,
        ProductRow.id,
    )


def list_public_product_ids_page(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
    tags: set[str],
    page: int,
    page_size: int,
) -> list[UUID]:
    statement = _public_product_id_statement(
        session,
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
        tags=tags,
    )
    return [
        row.product_id
        for row in session.execute(
            statement.offset((page - 1) * page_size).limit(page_size)
        ).all()
    ]


def count_public_catalog_products(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
    tags: set[str],
) -> int:
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = _with_catalog_tag_filters(session, statement, tags=tags)
    matching_ids = (
        statement.with_only_columns(ProductRow.id)
        .order_by(None)
        .distinct()
        .subquery()
    )
    return int(
        session.scalar(select(func.count()).select_from(matching_ids)) or 0
    )


def list_all_public_catalog_rows(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
):
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=None,
    )
    return list(
        session.execute(
            _ordered_public_catalog_statement(statement, query="")
        ).all()
    )


def count_public_catalog_rows(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
    tags: set[str],
) -> int:
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = _with_catalog_tag_filters(session, statement, tags=tags)
    matching_ids = (
        statement.with_only_columns(PublicCatalogOfferRow.id)
        .order_by(None)
        .subquery()
    )
    return int(
        session.scalar(select(func.count()).select_from(matching_ids)) or 0
    )


def list_public_catalog_category_ids(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
) -> set[UUID]:
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = (
        statement.with_only_columns(ProductRow.category_id)
        .where(ProductRow.category_id.is_not(None))
        .order_by(None)
        .distinct()
    )
    return set(session.scalars(statement).all())


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


def get_catalog_category(
    session: Session,
    *,
    tenant_id: UUID,
    category_id: UUID,
) -> ProductCategoryRow | None:
    return session.scalar(
        select(ProductCategoryRow).where(
            ProductCategoryRow.tenant_id == tenant_id,
            ProductCategoryRow.id == category_id,
        )
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


def list_public_catalog_rows_by_product_ids(
    session: Session,
    *,
    tenant_id: UUID,
    product_ids: list[UUID],
    now: datetime,
    category: str | None,
):
    if not product_ids:
        return []
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=category,
    ).where(ProductRow.id.in_(product_ids))
    return list(session.execute(statement).all())


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


def approved_image_for_product(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> ProductImageRow | None:
    return session.scalar(
        select(ProductImageRow)
        .where(
            ProductImageRow.tenant_id == tenant_id,
            ProductImageRow.product_id == product_id,
            ProductImageRow.approval_status == "APPROVED",
        )
        .order_by(
            case((ProductImageRow.image_role == "MAIN", 0), else_=1),
            ProductImageRow.sort_order,
            ProductImageRow.id,
        )
        .limit(1)
    )


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
