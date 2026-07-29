from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..repositories import public_catalog_repository
from ..repositories import storefront_analytics_repository as repository
from ..services.catalog_translation import catalog_translation_source
from ..services.storefront_analytics import raw_ip_retention_days
from ..storefront_analytics_schemas import (
    StorefrontAnalyticsCountryPoint,
    StorefrontAnalyticsCountryProductPoint,
    StorefrontAnalyticsDailyPoint,
    StorefrontAnalyticsProductPoint,
    StorefrontAnalyticsResponse,
    StorefrontAnalyticsSummary,
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


def get_storefront_analytics(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    days: int,
) -> StorefrontAnalyticsResponse:
    if "analytics.view" not in permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            "analytics.view permission is required.",
            kind="forbidden",
        )
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
    local_now = now.astimezone(zone)
    end_date = local_now.date()
    start_date = end_date - timedelta(days=days - 1)
    started_at = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(UTC)
    ended_at = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=zone,
    ).astimezone(UTC)

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
