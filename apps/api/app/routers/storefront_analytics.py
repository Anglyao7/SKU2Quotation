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
    StorefrontAnalyticsResponse,
    StorefrontProductViewCreate,
)
from ..use_cases import storefront_analytics as use_cases
from .errors import application_http_error


router = APIRouter(tags=["storefront-analytics"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


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
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
