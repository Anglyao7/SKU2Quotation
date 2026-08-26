from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog_merchandising import (
    POPULAR_CATEGORY_CODE,
    POPULAR_CATEGORY_COLOR,
    POPULAR_CATEGORY_NAME,
)
from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..product_center_models import ProductAuditEventRow
from ..product_supplier_models import ProductCategoryRow, ProductRow
from ..repositories import public_catalog_repository
from ..repositories import storefront_analytics_repository as repository
from ..services.catalog_translation import catalog_translation_source
from ..services.storefront_analytics import raw_ip_retention_days
from ..services.platform_usage import record_storefront_visit
from ..services.catalog_write_guard import (
    lock_catalog_write,
    release_rollback_ownership,
)
from ..storefront_analytics_schemas import (
    StorefrontAnalyticsCountryPoint,
    StorefrontAnalyticsCountryProductPoint,
    StorefrontAnalyticsDailyPoint,
    StorefrontAnalyticsProductPoint,
    StorefrontAnalyticsResponse,
    StorefrontAnalyticsSummary,
    PopularCategoryAssignResponse,
    StorefrontProductRankingItem,
    StorefrontProductRankingResponse,
)


def _resolve_public_store(session: Session, *, slug: str) -> TenantRow:
    profile = public_catalog_repository.find_published_profile_by_slug(
        session,
        slug=slug.casefold().strip(),
    )
    if profile is None:
        raise ApplicationError(
            "STORE_NOT_FOUND",
            "Store was not found.",
            kind="not_found",
        )
    set_public_tenant_context(session, tenant_id=profile.tenant_id)
    tenant = public_catalog_repository.get_active_tenant(
        session,
        tenant_id=profile.tenant_id,
    )
    if tenant is None:
        raise ApplicationError(
            "STORE_NOT_FOUND",
            "Store was not found.",
            kind="not_found",
        )
    return tenant


def _tenant_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _require(permissions: frozenset[str], permission: str) -> None:
    if permission not in permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            f"Permission required: {permission}",
            kind="forbidden",
        )


def _analytics_date_window(
    session: Session,
    *,
    tenant_id: UUID,
    days: int,
) -> tuple[TenantRow, datetime, str, ZoneInfo, datetime, datetime]:
    tenant = session.get(TenantRow, tenant_id)
    if tenant is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND",
            "Tenant was not found.",
            kind="not_found",
        )
    now = utcnow()
    timezone_name = tenant.timezone or "UTC"
    zone = _tenant_zone(timezone_name)
    if zone.key == "UTC" and timezone_name != "UTC":
        timezone_name = "UTC"
    end_date = now.astimezone(zone).date()
    start_date = end_date - timedelta(days=days - 1)
    started_at = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(UTC)
    ended_at = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=zone,
    ).astimezone(UTC)
    return tenant, now, timezone_name, zone, started_at, ended_at


def record_product_view(
    session: Session,
    *,
    slug: str,
    sku_id: UUID,
    event_id: str,
    ip_address: str,
    country_code: str,
) -> tuple[UUID, bool]:
    tenant = _resolve_public_store(session, slug=slug)
    rows = public_catalog_repository.list_public_catalog_rows_by_sku_ids(
        session,
        tenant_id=tenant.id,
        sku_ids=[sku_id],
        now=utcnow(),
    )
    if not rows:
        raise ApplicationError(
            "PUBLIC_SKU_NOT_FOUND",
            "Public SKU was not found.",
            kind="not_found",
        )
    _offer, sku, product, _category = rows[0]
    source = catalog_translation_source(rows[0])
    now = utcnow()
    recorded = repository.insert_event_if_absent(
        session,
        tenant_id=tenant.id,
        event_id=event_id,
        product_id=product.id,
        sku_id=sku.id,
        sku_code=sku.sku_code,
        product_name=source.name,
        ip_address=ip_address,
        country_code=country_code,
        now=now,
    )
    if not recorded:
        return tenant.id, False

    repository.increment_daily_view(
        session,
        tenant_id=tenant.id,
        viewed_on=now.astimezone(_tenant_zone(tenant.timezone)).date(),
        product_id=product.id,
        sku_id=sku.id,
        sku_code=sku.sku_code,
        product_name=source.name,
        country_code=country_code,
        now=now,
    )
    session.commit()
    return tenant.id, True


def record_storefront_visit_event(
    session: Session,
    *,
    slug: str,
    event_id: str,
    ip_address: str,
    country_code: str,
) -> tuple[UUID, bool]:
    """Record an anonymous storefront entry for platform-level usage metrics."""

    tenant = _resolve_public_store(session, slug=slug)
    recorded = record_storefront_visit(
        session,
        tenant_id=tenant.id,
        event_id=event_id,
        ip_address=ip_address,
        country_code=country_code,
    )
    session.commit()
    return tenant.id, recorded


def get_storefront_analytics(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    days: int,
) -> StorefrontAnalyticsResponse:
    _require(permissions, "analytics.view")
    _tenant, now, timezone_name, zone, started_at, ended_at = (
        _analytics_date_window(session, tenant_id=tenant_id, days=days)
    )
    start_date = started_at.astimezone(zone).date()
    end_date = (ended_at - timedelta(microseconds=1)).astimezone(zone).date()

    total_views, viewed_products, identified_countries = repository.totals(
        session,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
    )
    unique_visitors = repository.unique_visitor_count(
        session,
        tenant_id=tenant_id,
        started_at=started_at,
        ended_at=ended_at,
    )

    daily_by_date = dict(
        repository.daily_views(
            session,
            tenant_id=tenant_id,
            start_date=start_date,
            end_date=end_date,
        )
    )
    daily = [
        StorefrontAnalyticsDailyPoint(
            date=start_date + timedelta(days=offset),
            views=daily_by_date.get(start_date + timedelta(days=offset), 0),
        )
        for offset in range(days)
    ]
    country_rows = repository.top_countries(
        session,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        limit=8,
    )
    countries = [
        StorefrontAnalyticsCountryPoint(
            country_code=country_code,
            views=views,
            share=(views / total_views if total_views else 0),
        )
        for country_code, views in country_rows
    ]
    product_rows = repository.top_products(
        session,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        limit=10,
    )
    products = [
        StorefrontAnalyticsProductPoint(
            product_id=product_id,
            sku_id=product_sku_id,
            sku_code=sku_code,
            name=name,
            views=views,
        )
        for product_id, product_sku_id, sku_code, name, views in product_rows
    ]
    country_products = [
        StorefrontAnalyticsCountryProductPoint(
            country_code=country_code,
            sku_id=product_sku_id,
            views=views,
        )
        for country_code, product_sku_id, views in repository.country_product_views(
            session,
            tenant_id=tenant_id,
            start_date=start_date,
            end_date=end_date,
            country_codes=[item.country_code for item in countries],
            sku_ids=[item.sku_id for item in products[:8]],
        )
    ]
    return StorefrontAnalyticsResponse(
        generated_at=now,
        timezone=timezone_name,
        start_date=start_date,
        end_date=end_date,
        days=days,
        raw_ip_retention_days=raw_ip_retention_days(),
        summary=StorefrontAnalyticsSummary(
            total_views=total_views,
            unique_visitors=unique_visitors,
            viewed_products=viewed_products,
            identified_countries=identified_countries,
        ),
        daily=daily,
        countries=countries,
        products=products,
        country_products=country_products,
    )


def get_product_ranking(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    days: int,
    page: int,
    page_size: int,
) -> StorefrontProductRankingResponse:
    """Return a product-level ranking suitable for merchant bulk actions."""

    _require(permissions, "analytics.view")
    _tenant, _now, _timezone_name, zone, started_at, ended_at = (
        _analytics_date_window(session, tenant_id=tenant_id, days=days)
    )
    start_date = started_at.astimezone(zone).date()
    end_date = (ended_at - timedelta(microseconds=1)).astimezone(zone).date()
    total, rows = repository.product_ranking(
        session,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    rank_offset = (page - 1) * page_size
    return StorefrontProductRankingResponse(
        start_date=start_date,
        end_date=end_date,
        days=days,
        page=page,
        page_size=page_size,
        total=total,
        items=[
            StorefrontProductRankingItem(
                rank=rank_offset + index,
                product_id=row.product_id,
                product_code=row.product_code,
                name=row.name,
                category_id=row.category_id,
                category_name=row.category_name,
                views=row.views,
                is_pinned=row.is_pinned,
                is_popular=(row.category_code or "").upper()
                == POPULAR_CATEGORY_CODE,
            )
            for index, row in enumerate(rows, start=1)
        ],
    )


def assign_products_to_popular_category(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    product_ids: list[UUID],
) -> PopularCategoryAssignResponse:
    """Move selected products into the tenant's stable, system-managed hot category."""

    _require(permissions, "analytics.view")
    _require(permissions, "product.edit")
    lock_catalog_write(session, tenant_id=tenant_id)
    products = list(
        session.scalars(
            select(ProductRow).where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.id.in_(product_ids),
                ProductRow.deleted_at.is_(None),
                ProductRow.status != "ARCHIVED",
            )
        ).all()
    )
    found_ids = {row.id for row in products}
    missing_ids = [product_id for product_id in product_ids if product_id not in found_ids]
    if missing_ids:
        raise ApplicationError(
            "PRODUCT_NOT_FOUND",
            "部分商品不存在或已经归档，请刷新排行榜后重试。",
            kind="not_found",
        )
    release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        product_ids=[row.id for row in products],
    )

    now = utcnow()
    popular = session.scalar(
        select(ProductCategoryRow)
        .where(
            ProductCategoryRow.tenant_id == tenant_id,
            func.upper(ProductCategoryRow.code) == POPULAR_CATEGORY_CODE,
        )
        .execution_options(include_deleted=True)
    )
    if popular is None:
        popular = session.scalar(
            select(ProductCategoryRow)
            .where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.parent_id.is_(None),
                ProductCategoryRow.deleted_at.is_(None),
                func.lower(ProductCategoryRow.name)
                == POPULAR_CATEGORY_NAME.casefold(),
            )
            .order_by(ProductCategoryRow.sort_order, ProductCategoryRow.id)
        )
    category_before: dict[str, object] = {}
    if popular is None:
        popular = ProductCategoryRow(
            id=uuid4(),
            tenant_id=tenant_id,
            parent_id=None,
            code=POPULAR_CATEGORY_CODE,
            name=POPULAR_CATEGORY_NAME,
            path=POPULAR_CATEGORY_NAME,
            display_color=POPULAR_CATEGORY_COLOR,
            status="ACTIVE",
            sort_order=0,
        )
        session.add(popular)
        session.flush()
    else:
        category_before = {
            "code": popular.code,
            "name": popular.name,
            "parent_id": str(popular.parent_id) if popular.parent_id else None,
            "sort_order": popular.sort_order,
            "status": popular.status,
            "deleted": popular.deleted_at is not None,
        }
        category_state_before = (
            popular.parent_id,
            popular.code,
            popular.name,
            popular.path,
            popular.display_color,
            popular.status,
            popular.deleted_at,
        )
        popular.parent_id = None
        popular.code = POPULAR_CATEGORY_CODE
        popular.name = POPULAR_CATEGORY_NAME
        popular.path = POPULAR_CATEGORY_NAME
        popular.display_color = popular.display_color or POPULAR_CATEGORY_COLOR
        popular.status = "ACTIVE"
        popular.deleted_at = None
        popular.updated_at = now
        if category_state_before != (
            popular.parent_id,
            popular.code,
            popular.name,
            popular.path,
            popular.display_color,
            popular.status,
            popular.deleted_at,
        ):
            popular.version += 1

    root_categories = list(
        session.scalars(
            select(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.parent_id.is_(None),
                ProductCategoryRow.deleted_at.is_(None),
                ProductCategoryRow.id != popular.id,
            )
        ).all()
    )
    root_categories.sort(
        key=lambda row: (row.sort_order, row.name.casefold(), str(row.id))
    )
    ordered_roots = [popular, *root_categories]
    for sort_order, category in enumerate(ordered_roots):
        if category.sort_order == sort_order:
            continue
        category.sort_order = sort_order
        category.version += 1
        category.updated_at = now

    moved_count = 0
    for product in products:
        if product.category_id == popular.id:
            continue
        previous_category_id = product.category_id
        product.category_id = popular.id
        product.current_version += 1
        product.search_document_version = 0
        product.updated_by = user_id
        product.updated_at = now
        moved_count += 1
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product.id,
                entity_type="PRODUCT",
                entity_id=str(product.id),
                action="product.category_marked_popular",
                before={
                    "category_id": str(previous_category_id)
                    if previous_category_id
                    else None
                },
                after={
                    "category_id": str(popular.id),
                    "category_code": POPULAR_CATEGORY_CODE,
                },
                actor_membership_id=membership_id,
                occurred_at=now,
            )
        )

    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="CATEGORY",
            entity_id=str(popular.id),
            action="category.popular_products_assigned",
            before=category_before,
            after={
                "code": POPULAR_CATEGORY_CODE,
                "name": POPULAR_CATEGORY_NAME,
                "sort_order": 0,
                "selected_count": len(product_ids),
                "moved_count": moved_count,
            },
            actor_membership_id=membership_id,
            occurred_at=now,
        )
    )
    try:
        session.flush()
        popular_product_count = int(
            session.scalar(
                select(func.count(ProductRow.id)).where(
                    ProductRow.tenant_id == tenant_id,
                    ProductRow.category_id == popular.id,
                    ProductRow.deleted_at.is_(None),
                    ProductRow.status != "ARCHIVED",
                )
            )
            or 0
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "POPULAR_CATEGORY_ASSIGN_FAILED",
            "归入热门失败，请刷新后重试。",
            kind="conflict",
        ) from exc

    return PopularCategoryAssignResponse(
        category_id=popular.id,
        category_name=POPULAR_CATEGORY_NAME,
        selected_count=len(product_ids),
        moved_count=moved_count,
        popular_product_count=popular_product_count,
    )
