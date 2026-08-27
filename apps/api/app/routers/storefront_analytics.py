from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from ..database import get_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..services.storefront_analytics import (
    cleanup_expired_raw_events,
    mark_cleanup_scheduled,
    request_country_code,
    request_visitor_ip,
)
from ..storefront_analytics_schemas import (
    PopularCategoryAssignRequest,
    PopularCategoryAssignResponse,
    StorefrontAnalyticsResponse,
    StorefrontProductRankingResponse,
    StorefrontVisitCreate,
    StorefrontProductViewCreate,
)
from ..use_cases import storefront_analytics as use_cases
from .errors import application_http_error


router = APIRouter(tags=["storefront-analytics"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.post(
    "/api/store/{tenant_slug}/visits",
    status_code=status.HTTP_204_NO_CONTENT,
)
def record_storefront_visit(
    tenant_slug: str,
    payload: StorefrontVisitCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> None:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-storefront-visit",
        limit=configured_limit("RATE_LIMIT_PUBLIC_STOREFRONT_VISIT_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_PUBLIC_STOREFRONT_VISIT_WINDOW_SECONDS",
            60,
            maximum=86_400,
        ),
    )
    visitor_ip = request_visitor_ip(request)
    country_code = request_country_code(request, visitor_ip=visitor_ip)
    try:
        use_cases.record_storefront_visit_event(
            session,
            slug=tenant_slug,
            event_id=payload.event_id,
            ip_address=visitor_ip,
            country_code=country_code,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/store/{tenant_slug}/skus/{sku_id}/views",
    status_code=status.HTTP_204_NO_CONTENT,
)
def record_storefront_product_view(
    tenant_slug: str,
    sku_id: UUID,
    payload: StorefrontProductViewCreate,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> None:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-storefront-product-view",
        limit=configured_limit(
            "RATE_LIMIT_PUBLIC_STOREFRONT_VIEW_REQUESTS",
            180,
        ),
        window_seconds=configured_limit(
            "RATE_LIMIT_PUBLIC_STOREFRONT_VIEW_WINDOW_SECONDS",
            60,
            maximum=86_400,
        ),
    )
    visitor_ip = request_visitor_ip(request)
    country_code = request_country_code(request, visitor_ip=visitor_ip)
    try:
        tenant_id, _recorded = use_cases.record_product_view(
            session,
            slug=tenant_slug,
            sku_id=sku_id,
            event_id=payload.event_id,
            ip_address=visitor_ip,
            country_code=country_code,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    if mark_cleanup_scheduled(tenant_id):
        background_tasks.add_task(cleanup_expired_raw_events, tenant_id)


@router.get(
    "/api/v1/storefront-analytics",
    response_model=StorefrontAnalyticsResponse,
)
def storefront_analytics(
    response: Response,
    days: int = Query(default=30, ge=7, le=60),
    session: Session = Depends(get_authenticated_session),
) -> StorefrontAnalyticsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_storefront_analytics(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            days=days,
            account_scope=context.account_scope,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/storefront-analytics/product-ranking",
    response_model=StorefrontProductRankingResponse,
)
def storefront_product_ranking(
    response: Response,
    days: int = Query(default=30, ge=7, le=60),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_authenticated_session),
) -> StorefrontProductRankingResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_product_ranking(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            days=days,
            page=page,
            page_size=page_size,
            account_scope=context.account_scope,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/storefront-analytics/popular-category",
    response_model=PopularCategoryAssignResponse,
)
def assign_storefront_popular_category(
    payload: PopularCategoryAssignRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PopularCategoryAssignResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.assign_products_to_popular_category(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            product_ids=payload.product_ids,
            account_scope=context.account_scope,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
