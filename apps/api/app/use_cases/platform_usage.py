from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..platform_usage_schemas import (
    PlatformTenantUsageItem,
    PlatformUsageResponse,
    PlatformUsageTotals,
)
from ..repositories import platform_usage_repository as repository
from ..services.auth.dependencies import RequestContext


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def get_platform_usage(
    session: Session,
    *,
    context: RequestContext,
    days: int,
) -> PlatformUsageResponse:
    _require_platform_admin(context)
    now = utcnow()
    started_at = now - timedelta(days=days)
    rows = repository.list_usage(
        session,
        started_at=started_at,
        ended_at=now,
        start_date=started_at.date(),
        end_date=now.date(),
    )
    items: list[PlatformTenantUsageItem] = []
    for row in rows:
        status = str(row["status"] or "active")
        items.append(
            PlatformTenantUsageItem(
                tenant_id=row["id"],
                name=str(row["name"] or ""),
                slug=str(row["slug"] or ""),
                status=status,
                active=status == "active",
                storefront_visitors=int(row["storefront_visitors"] or 0),
                product_visitors=int(row["product_visitors"] or 0),
                product_clicks=int(row["product_clicks"] or 0),
                quote_requests=int(row["quote_requests"] or 0),
                quotations=int(row["quotations"] or 0),
                image_searches=int(row["image_searches"] or 0),
                ai_conversations=int(row["ai_conversations"] or 0),
                ai_messages=int(row["ai_messages"] or 0),
            )
        )

    total_fields = (
        "storefront_visitors",
        "product_visitors",
        "product_clicks",
        "quote_requests",
        "quotations",
        "image_searches",
        "ai_conversations",
        "ai_messages",
    )
    totals = PlatformUsageTotals(
        **{
            field: sum(int(getattr(item, field)) for item in items)
            for field in total_fields
        }
    )
    return PlatformUsageResponse(
        generated_at=now,
        start_date=started_at.date(),
        end_date=now.date(),
        days=days,
        totals=totals,
        tenants=items,
    )
