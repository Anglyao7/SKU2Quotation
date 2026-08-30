from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Text, case, cast, exists, func, or_, select, update
from sqlalchemy.orm import Load, Session, aliased

from ..catalog_merchandising import POPULAR_CATEGORY_CODE
from ..identity_models import MembershipRow, TenantRow
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductCategoryRow, ProductImageRow, ProductRow
from ..public_catalog_models import (
    PublicCatalogOfferRow,
    PublicQuoteDownloadTokenRow,
    PublicQuoteDraftItemRow,
    PublicQuoteDraftRow,
    StorefrontOrderRecordRow,
    TenantPublicProfileRow,
)
from ..storefront_analytics_models import StorefrontProductViewDailyRow

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
                func.lower(func.coalesce(SkuRow.source_sku_code, "")).contains(
                    normalized
                ),
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
            case(
                (
                    or_(
                        func.lower(SkuRow.sku_code) == normalized,
                        func.lower(func.coalesce(SkuRow.source_sku_code, ""))
                        == normalized,
                    ),
                    0,
                ),
                else_=1,
            ),
            ProductRow.name,
            SkuRow.sku_code,
            SkuRow.id,
        )
    return statement.order_by(
        # A merchant pin is a storefront-wide merchandising override.  Keep it
        # ahead of category order so a product from a later category can still
        # reach the first page of "all products".  A category filter naturally
        # scopes the same rule to that category.
        case((ProductRow.storefront_pinned_at.is_not(None), 0), else_=1),
        ProductRow.storefront_pinned_at.desc(),
        case(
            (
                func.upper(
                    func.coalesce(
                        ParentProductCategoryRow.code,
                        ProductCategoryRow.code,
                        "",
                    )
                )
                == POPULAR_CATEGORY_CODE,
                0,
            ),
            else_=1,
        ),
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
        func.lower(func.coalesce(SkuRow.source_sku_code, "")),
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


def list_public_catalog_exact_candidates(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    query: str,
    category: str | None,
    limit: int,
):
    """Return published rows whose customer-visible name or SKU exactly matches.

    Exact catalog lookup is deliberately independent from the embedding index and
    from the bounded n-gram candidate pool.  A copied product title must remain
    discoverable even when a large catalog fills that broader candidate window.
    """

    normalized = query.casefold().strip()
    if not normalized:
        return []
    sku_code = func.lower(SkuRow.sku_code)
    source_sku_code = func.lower(func.coalesce(SkuRow.source_sku_code, ""))
    sku_name = func.lower(func.coalesce(SkuRow.name, ""))
    product_name = func.lower(ProductRow.name)
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=category,
    ).where(
        or_(
            sku_code == normalized,
            source_sku_code == normalized,
            sku_name == normalized,
            product_name == normalized,
        )
    )
    statement = statement.order_by(
        case(
            (or_(sku_code == normalized, source_sku_code == normalized), 0),
            (product_name == normalized, 1),
            else_=2,
        ),
        ProductRow.name,
        SkuRow.sku_code,
        SkuRow.id,
    )
    return list(session.execute(statement.limit(max(1, limit))).all())


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
    product_ids: set[UUID] | None = None,
    excluded_product_ids: set[UUID] | None = None,
    hot: bool = False,
):
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = _with_catalog_tag_filters(session, statement, tags=tags)
    if product_ids is not None:
        if not product_ids:
            statement = statement.where(ProductRow.id.is_(None))
        else:
            statement = statement.where(ProductRow.id.in_(product_ids))
    if excluded_product_ids:
        # Keep account-level hidden products out of the count and the page
        # query itself.  Filtering after pagination would create short pages
        # and, more importantly, could leak a hidden product through facets.
        statement = statement.where(~ProductRow.id.in_(excluded_product_ids))
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
    pinned_rank = case((ProductRow.storefront_pinned_at.is_not(None), 0), else_=1)
    pinned_at = ProductRow.storefront_pinned_at
    popular_rank = case(
        (
            func.upper(
                func.coalesce(
                    ParentProductCategoryRow.code,
                    ProductCategoryRow.code,
                    "",
                )
            )
            == POPULAR_CATEGORY_CODE,
            0,
        ),
        else_=1,
    )
    product_name = func.lower(ProductRow.name)
    normalized = query.casefold().strip()
    match_rank = func.min(
        case(
            (func.lower(SkuRow.sku_code) == normalized, 0),
            (
                func.lower(func.coalesce(SkuRow.source_sku_code, ""))
                == normalized,
                0,
            ),
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
            pinned_rank.label("pinned_rank"),
            pinned_at.label("pinned_at"),
            popular_rank.label("popular_rank"),
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
            pinned_rank,
            pinned_at,
            popular_rank,
            product_name,
        )
    )
    if normalized:
        return grouped.order_by(
            match_rank,
            pinned_rank,
            pinned_at.desc(),
            popular_rank,
            uncategorized,
            root_sort,
            root_name,
            child_sort,
            child_name,
            product_name,
            ProductRow.id,
        )
    if hot:
        catalog_products = grouped.subquery("public_catalog_products")
        view_totals = (
            select(
                StorefrontProductViewDailyRow.product_id.label("product_id"),
                func.sum(StorefrontProductViewDailyRow.view_count).label(
                    "view_count"
                ),
            )
            .where(
                StorefrontProductViewDailyRow.tenant_id == tenant_id,
                StorefrontProductViewDailyRow.viewed_on
                >= (now - timedelta(days=90)).date(),
            )
            .group_by(StorefrontProductViewDailyRow.product_id)
            .subquery("hot_product_views")
        )
        order_totals = (
            select(
                PublicQuoteDraftItemRow.product_id_snapshot.label("product_id"),
                func.count(
                    func.distinct(PublicQuoteDraftItemRow.quote_draft_id)
                ).label("order_count"),
            )
            .join(
                PublicQuoteDraftRow,
                (PublicQuoteDraftRow.tenant_id == PublicQuoteDraftItemRow.tenant_id)
                & (PublicQuoteDraftRow.id == PublicQuoteDraftItemRow.quote_draft_id),
            )
            .where(
                PublicQuoteDraftItemRow.tenant_id == tenant_id,
                PublicQuoteDraftItemRow.deleted_at.is_(None),
                PublicQuoteDraftRow.tenant_id == tenant_id,
                PublicQuoteDraftRow.deleted_at.is_(None),
                PublicQuoteDraftRow.status.in_(
                    ("PENDING_CONFIRMATION", "CONFIRMED")
                ),
                PublicQuoteDraftRow.created_at >= now - timedelta(days=90),
            )
            .group_by(PublicQuoteDraftItemRow.product_id_snapshot)
            .subquery("hot_product_orders")
        )
        view_count = func.coalesce(view_totals.c.view_count, 0)
        order_count = func.coalesce(order_totals.c.order_count, 0)
        hot_score = view_count + order_count * 20
        return (
            select(catalog_products.c.product_id)
            .outerjoin(
                view_totals,
                view_totals.c.product_id == catalog_products.c.product_id,
            )
            .outerjoin(
                order_totals,
                order_totals.c.product_id == catalog_products.c.product_id,
            )
            .order_by(
                catalog_products.c.pinned_rank,
                catalog_products.c.pinned_at.desc(),
                catalog_products.c.popular_rank,
                hot_score.desc(),
                order_count.desc(),
                view_count.desc(),
                catalog_products.c.uncategorized,
                catalog_products.c.root_sort,
                catalog_products.c.root_name,
                catalog_products.c.child_sort,
                catalog_products.c.child_name,
                catalog_products.c.product_name,
                catalog_products.c.product_id,
            )
        )
    return grouped.order_by(
        pinned_rank,
        pinned_at.desc(),
        popular_rank,
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
    product_ids: set[UUID] | None = None,
    excluded_product_ids: set[UUID] | None = None,
    hot: bool = False,
) -> list[UUID]:
    statement = _public_product_id_statement(
        session,
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
        tags=tags,
        product_ids=product_ids,
        excluded_product_ids=excluded_product_ids,
        hot=hot,
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
    product_ids: set[UUID] | None = None,
    excluded_product_ids: set[UUID] | None = None,
) -> int:
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    statement = _with_catalog_tag_filters(session, statement, tags=tags)
    if product_ids is not None:
        if not product_ids:
            return 0
        statement = statement.where(ProductRow.id.in_(product_ids))
    if excluded_product_ids:
        statement = statement.where(~ProductRow.id.in_(excluded_product_ids))
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


def list_all_public_catalog_translation_rows(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
):
    """Load only the public catalog fields used by translation hashing."""

    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=None,
    ).options(
        Load(PublicCatalogOfferRow).load_only(
            PublicCatalogOfferRow.id,
            PublicCatalogOfferRow.tags,
            PublicCatalogOfferRow.display_tag,
            PublicCatalogOfferRow.updated_at,
        ),
        Load(SkuRow).load_only(
            SkuRow.id,
            SkuRow.sku_code,
            SkuRow.name,
            SkuRow.option_values,
            SkuRow.version,
            SkuRow.updated_at,
        ),
        Load(ProductRow).load_only(
            ProductRow.id,
            ProductRow.name,
            ProductRow.description,
            ProductRow.current_version,
            ProductRow.updated_at,
        ),
        Load(ProductCategoryRow).load_only(
            ProductCategoryRow.id,
            ProductCategoryRow.code,
            ProductCategoryRow.name,
            ProductCategoryRow.path,
            ProductCategoryRow.updated_at,
        ),
    )
    # Hashes sort their own identities, so the storefront's merchandising
    # order is unnecessary for this administrative calculation.
    return list(session.execute(statement.order_by(ProductRow.id, SkuRow.id)).all())


def list_public_catalog_product_ids(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
) -> list[UUID]:
    """Return products that currently have at least one customer-visible offer."""

    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=None,
    )
    return list(
        session.scalars(
            statement.with_only_columns(ProductRow.id)
            .order_by(None)
            .distinct()
            .order_by(ProductRow.id)
        ).all()
    )


def list_public_catalog_rows_for_products(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    product_ids: list[UUID],
):
    """Load current public catalog facts for a bounded ranked product set."""

    ordered_ids = list(dict.fromkeys(product_ids))
    if not ordered_ids:
        return []
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query="",
        category=None,
    ).where(ProductRow.id.in_(ordered_ids))
    return list(session.execute(statement.order_by(ProductRow.id, SkuRow.id)).all())


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
    product_ids: set[UUID] | None = None,
    excluded_product_ids: set[UUID] | None = None,
) -> set[UUID]:
    statement = _public_catalog_statement(
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
    )
    if product_ids is not None:
        if not product_ids:
            return set()
        statement = statement.where(ProductRow.id.in_(product_ids))
    if excluded_product_ids:
        statement = statement.where(~ProductRow.id.in_(excluded_product_ids))
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
            ProductCategoryRow.deleted_at.is_(None),
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
            ProductImageRow.deleted_at.is_(None),
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
            ProductImageRow.deleted_at.is_(None),
        )
        .order_by(
            case((ProductImageRow.image_role == "MAIN", 0), else_=1),
            ProductImageRow.sort_order,
            ProductImageRow.id,
        )
        .limit(1)
    )


def approved_images_for_product(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> list[ProductImageRow]:
    """Return the complete public gallery in its storefront display order."""

    return list(
        session.scalars(
            select(ProductImageRow)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.product_id == product_id,
                ProductImageRow.approval_status == "APPROVED",
                ProductImageRow.content_type.like("image/%"),
                ProductImageRow.deleted_at.is_(None),
            )
            .order_by(
                case((ProductImageRow.image_role == "MAIN", 0), else_=1),
                ProductImageRow.sort_order,
                ProductImageRow.id,
            )
        ).all()
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
            ProductImageRow.deleted_at.is_(None),
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
    session: Session,
    *,
    tenant_id: UUID,
    quote_draft_id: UUID,
    for_update: bool = False,
) -> PublicQuoteDraftRow | None:
    statement = select(PublicQuoteDraftRow).where(
        PublicQuoteDraftRow.tenant_id == tenant_id,
        PublicQuoteDraftRow.id == quote_draft_id,
    )
    if for_update:
        statement = statement.with_for_update(of=PublicQuoteDraftRow)
    return session.scalar(statement)


def get_quote_draft_by_quotation_number(
    session: Session,
    *,
    tenant_id: UUID,
    quotation_number: str,
) -> PublicQuoteDraftRow | None:
    return session.scalar(
        select(PublicQuoteDraftRow).where(
            PublicQuoteDraftRow.tenant_id == tenant_id,
            PublicQuoteDraftRow.quotation_number == quotation_number,
            PublicQuoteDraftRow.deleted_at.is_(None),
        )
    )


def get_storefront_order_record_by_quote(
    session: Session,
    *,
    tenant_id: UUID,
    quote_draft_id: UUID,
    for_update: bool = False,
) -> StorefrontOrderRecordRow | None:
    statement = select(StorefrontOrderRecordRow).where(
        StorefrontOrderRecordRow.tenant_id == tenant_id,
        StorefrontOrderRecordRow.source_quote_draft_id == quote_draft_id,
        StorefrontOrderRecordRow.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update(of=StorefrontOrderRecordRow)
    return session.scalar(statement)


def add_storefront_order_record(
    session: Session,
    *,
    record: StorefrontOrderRecordRow,
) -> None:
    session.add(record)
    session.flush()


def storefront_order_statistics_rows(
    session: Session,
    *,
    tenant_id: UUID,
    start_at: datetime,
    end_at: datetime,
    submitted_by_membership_id: UUID | None = None,
) -> list[tuple[str, str, int, Decimal]]:
    statement = select(
        StorefrontOrderRecordRow.currency,
        StorefrontOrderRecordRow.status,
        func.count(StorefrontOrderRecordRow.id),
        func.coalesce(func.sum(StorefrontOrderRecordRow.total_amount), 0),
    ).where(
        StorefrontOrderRecordRow.tenant_id == tenant_id,
        StorefrontOrderRecordRow.confirmed_at >= start_at,
        StorefrontOrderRecordRow.confirmed_at < end_at,
        StorefrontOrderRecordRow.deleted_at.is_(None),
    )
    if submitted_by_membership_id is not None:
        statement = statement.where(
            StorefrontOrderRecordRow.submitted_by_membership_id
            == submitted_by_membership_id
        )
    return list(
        session.execute(
            statement.group_by(
                StorefrontOrderRecordRow.currency,
                StorefrontOrderRecordRow.status,
            ).order_by(
                StorefrontOrderRecordRow.currency,
                StorefrontOrderRecordRow.status,
            )
        ).all()
    )


def list_quote_drafts(
    session: Session,
    *,
    tenant_id: UUID,
    limit: int,
    owner_membership_id: UUID | None = None,
    parent_membership_id: UUID | None = None,
) -> list[PublicQuoteDraftRow]:
    """Load the quote inbox with ownership filtering before pagination.

    A child account must only receive its own queue.  A parent receives
    merchant-created drafts plus drafts created by direct children, but never a
    sibling child’s draft.  Applying the predicate in SQL avoids the old
    ``limit -> filter`` hole where a page could be empty even though visible
    records existed later in the inbox.
    """

    statement = select(PublicQuoteDraftRow).where(
        PublicQuoteDraftRow.tenant_id == tenant_id
    )
    owner_column = PublicQuoteDraftRow.submitted_by_membership_id
    if owner_membership_id is not None:
        statement = statement.where(owner_column == owner_membership_id)
    elif parent_membership_id is not None:
        child_ids = select(MembershipRow.id).where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.account_scope == "CUSTOMER_SUBACCOUNT",
            MembershipRow.status.in_(("active", "suspended")),
            MembershipRow.deleted_at.is_(None),
        )
        direct_child_ids = child_ids.where(
            MembershipRow.parent_membership_id == parent_membership_id
        )
        statement = statement.where(
            or_(
                owner_column.is_(None),
                ~owner_column.in_(child_ids),
                owner_column.in_(direct_child_ids),
            )
        )
    return list(
        session.scalars(
            statement.order_by(
                PublicQuoteDraftRow.created_at.desc(), PublicQuoteDraftRow.id
            ).limit(limit)
        ).all()
    )


def list_quote_drafts_by_visitor_token_hash(
    session: Session,
    *,
    tenant_id: UUID,
    visitor_token_hash: str,
    now: datetime,
    limit: int = 100,
) -> list[PublicQuoteDraftRow]:
    return list(
        session.scalars(
            select(PublicQuoteDraftRow)
            .where(
                PublicQuoteDraftRow.tenant_id == tenant_id,
                PublicQuoteDraftRow.visitor_token_hash == visitor_token_hash,
                PublicQuoteDraftRow.visitor_token_expires_at > now,
                PublicQuoteDraftRow.deleted_at.is_(None),
            )
            .order_by(
                PublicQuoteDraftRow.updated_at.desc(),
                PublicQuoteDraftRow.created_at.desc(),
                PublicQuoteDraftRow.id,
            )
            .limit(limit)
        ).all()
    )


def transition_quote_draft_status(
    session: Session,
    *,
    tenant_id: UUID,
    quote_draft_id: UUID,
    expected_status: str,
    target_status: str,
    updated_at: datetime,
) -> bool:
    result = session.execute(
        update(PublicQuoteDraftRow)
        .where(
            PublicQuoteDraftRow.tenant_id == tenant_id,
            PublicQuoteDraftRow.id == quote_draft_id,
            PublicQuoteDraftRow.status == expected_status,
            PublicQuoteDraftRow.deleted_at.is_(None),
        )
        .values(status=target_status, updated_at=updated_at)
    )
    return result.rowcount == 1


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


def get_quote_draft_item(
    session: Session,
    *,
    tenant_id: UUID,
    quote_draft_id: UUID,
    item_id: UUID,
    for_update: bool = False,
) -> PublicQuoteDraftItemRow | None:
    statement = select(PublicQuoteDraftItemRow).where(
        PublicQuoteDraftItemRow.tenant_id == tenant_id,
        PublicQuoteDraftItemRow.quote_draft_id == quote_draft_id,
        PublicQuoteDraftItemRow.id == item_id,
    )
    if for_update:
        statement = statement.with_for_update(of=PublicQuoteDraftItemRow)
    return session.scalar(statement)
