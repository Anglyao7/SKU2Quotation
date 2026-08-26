from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..identity_models import TenantRow
from ..image_intelligence_models import ImageSearchRow
from ..platform_usage_models import StorefrontVisitEventRow, TenantUsageDailyRow
from ..public_catalog_models import PublicQuoteDraftRow
from ..storefront_analytics_models import (
    StorefrontProductViewDailyRow,
    StorefrontProductViewEventRow,
)
from ..support_models import StorefrontChatConversationRow, StorefrontChatMessageRow
from ..trade_flow_models import QuotationRow


def list_usage(
    session: Session,
    *,
    started_at: datetime,
    ended_at: datetime,
    start_date: date,
    end_date: date,
) -> list[dict[str, object]]:
    """Aggregate usage in one SQL statement instead of querying every tenant."""

    product_clicks = (
        select(
            StorefrontProductViewDailyRow.tenant_id.label("tenant_id"),
            func.coalesce(func.sum(StorefrontProductViewDailyRow.view_count), 0).label(
                "product_clicks"
            ),
        )
        .where(
            StorefrontProductViewDailyRow.viewed_on >= start_date,
            StorefrontProductViewDailyRow.viewed_on <= end_date,
        )
        .group_by(StorefrontProductViewDailyRow.tenant_id)
        .subquery("usage_product_clicks")
    )
    product_visitors = (
        select(
            StorefrontProductViewEventRow.tenant_id.label("tenant_id"),
            func.count(func.distinct(StorefrontProductViewEventRow.ip_address)).label(
                "product_visitors"
            ),
        )
        .where(
            StorefrontProductViewEventRow.occurred_at >= started_at,
            StorefrontProductViewEventRow.occurred_at < ended_at,
        )
        .group_by(StorefrontProductViewEventRow.tenant_id)
        .subquery("usage_product_visitors")
    )
    storefront_visitors = (
        select(
            StorefrontVisitEventRow.tenant_id.label("tenant_id"),
            func.count(func.distinct(StorefrontVisitEventRow.visitor_key)).label(
                "storefront_visitors"
            ),
        )
        .where(
            StorefrontVisitEventRow.occurred_at >= started_at,
            StorefrontVisitEventRow.occurred_at < ended_at,
        )
        .group_by(StorefrontVisitEventRow.tenant_id)
        .subquery("usage_storefront_visitors")
    )
    quote_requests = (
        select(
            PublicQuoteDraftRow.tenant_id.label("tenant_id"),
            func.count(PublicQuoteDraftRow.id).label("quote_requests"),
        )
        .where(
            PublicQuoteDraftRow.created_at >= started_at,
            PublicQuoteDraftRow.created_at < ended_at,
        )
        .group_by(PublicQuoteDraftRow.tenant_id)
        .subquery("usage_quote_requests")
    )
    quotations = (
        select(
            QuotationRow.tenant_id.label("tenant_id"),
            func.count(QuotationRow.id).label("quotations"),
        )
        .where(
            QuotationRow.created_at >= started_at,
            QuotationRow.created_at < ended_at,
        )
        .group_by(QuotationRow.tenant_id)
        .subquery("usage_quotations")
    )
    stored_image_searches = (
        select(
            TenantUsageDailyRow.tenant_id.label("tenant_id"),
            func.coalesce(func.sum(TenantUsageDailyRow.image_search_count), 0).label(
                "stored_image_searches"
            ),
        )
        .where(
            TenantUsageDailyRow.usage_date >= start_date,
            TenantUsageDailyRow.usage_date <= end_date,
        )
        .group_by(TenantUsageDailyRow.tenant_id)
        .subquery("usage_stored_image_searches")
    )
    authenticated_image_searches = (
        select(
            ImageSearchRow.tenant_id.label("tenant_id"),
            func.count(ImageSearchRow.id).label("authenticated_image_searches"),
        )
        .where(
            ImageSearchRow.created_at >= started_at,
            ImageSearchRow.created_at < ended_at,
        )
        .group_by(ImageSearchRow.tenant_id)
        .subquery("usage_authenticated_image_searches")
    )
    ai_conversations = (
        select(
            StorefrontChatConversationRow.tenant_id.label("tenant_id"),
            func.count(StorefrontChatConversationRow.id).label("ai_conversations"),
        )
        .where(
            StorefrontChatConversationRow.created_at >= started_at,
            StorefrontChatConversationRow.created_at < ended_at,
        )
        .group_by(StorefrontChatConversationRow.tenant_id)
        .subquery("usage_ai_conversations")
    )
    ai_messages = (
        select(
            StorefrontChatMessageRow.tenant_id.label("tenant_id"),
            func.count(StorefrontChatMessageRow.id).label("ai_messages"),
        )
        .where(
            StorefrontChatMessageRow.created_at >= started_at,
            StorefrontChatMessageRow.created_at < ended_at,
            StorefrontChatMessageRow.sender_type == "AI",
        )
        .group_by(StorefrontChatMessageRow.tenant_id)
        .subquery("usage_ai_messages")
    )

    statement = (
        select(
            TenantRow.id,
            TenantRow.name,
            TenantRow.slug,
            TenantRow.status,
            TenantRow.created_at,
            func.coalesce(storefront_visitors.c.storefront_visitors, 0).label(
                "storefront_visitors"
            ),
            func.coalesce(product_visitors.c.product_visitors, 0).label(
                "product_visitors"
            ),
            func.coalesce(product_clicks.c.product_clicks, 0).label("product_clicks"),
            func.coalesce(quote_requests.c.quote_requests, 0).label("quote_requests"),
            func.coalesce(quotations.c.quotations, 0).label("quotations"),
            (
                func.coalesce(stored_image_searches.c.stored_image_searches, 0)
                + func.coalesce(
                    authenticated_image_searches.c.authenticated_image_searches, 0
                )
            ).label("image_searches"),
            func.coalesce(ai_conversations.c.ai_conversations, 0).label(
                "ai_conversations"
            ),
            func.coalesce(ai_messages.c.ai_messages, 0).label("ai_messages"),
        )
        .select_from(TenantRow)
        .outerjoin(storefront_visitors, storefront_visitors.c.tenant_id == TenantRow.id)
        .outerjoin(product_visitors, product_visitors.c.tenant_id == TenantRow.id)
        .outerjoin(product_clicks, product_clicks.c.tenant_id == TenantRow.id)
        .outerjoin(quote_requests, quote_requests.c.tenant_id == TenantRow.id)
        .outerjoin(quotations, quotations.c.tenant_id == TenantRow.id)
        .outerjoin(stored_image_searches, stored_image_searches.c.tenant_id == TenantRow.id)
        .outerjoin(
            authenticated_image_searches,
            authenticated_image_searches.c.tenant_id == TenantRow.id,
        )
        .outerjoin(ai_conversations, ai_conversations.c.tenant_id == TenantRow.id)
        .outerjoin(ai_messages, ai_messages.c.tenant_id == TenantRow.id)
        .order_by(TenantRow.name.asc(), TenantRow.id.asc())
    )
    return [dict(row._mapping) for row in session.execute(statement).all()]
