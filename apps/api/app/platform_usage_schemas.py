from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PlatformUsageTotals(BaseModel):
    storefront_visitors: int = Field(ge=0)
    product_visitors: int = Field(ge=0)
    product_clicks: int = Field(ge=0)
    quote_requests: int = Field(ge=0)
    quotations: int = Field(ge=0)
    image_searches: int = Field(ge=0)
    ai_conversations: int = Field(ge=0)
    ai_messages: int = Field(ge=0)


class PlatformTenantUsageItem(BaseModel):
    tenant_id: UUID
    name: str
    slug: str
    status: str
    active: bool
    storefront_visitors: int = Field(ge=0)
    product_visitors: int = Field(ge=0)
    product_clicks: int = Field(ge=0)
    quote_requests: int = Field(ge=0)
    quotations: int = Field(ge=0)
    image_searches: int = Field(ge=0)
    ai_conversations: int = Field(ge=0)
    ai_messages: int = Field(ge=0)


class PlatformUsageResponse(BaseModel):
    generated_at: datetime
    start_date: date
    end_date: date
    days: int = Field(ge=1, le=90)
    totals: PlatformUsageTotals
    tenants: list[PlatformTenantUsageItem]
