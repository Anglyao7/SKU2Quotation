from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class StorefrontProductViewCreate(BaseModel):
    event_id: str = Field(min_length=8, max_length=80)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:"
            for character in normalized
        ):
            raise ValueError("event_id contains unsupported characters")
        return normalized


class StorefrontAnalyticsSummary(BaseModel):
    total_views: int = Field(ge=0)
    unique_visitors: int = Field(ge=0)
    viewed_products: int = Field(ge=0)
    identified_countries: int = Field(ge=0)


class StorefrontAnalyticsDailyPoint(BaseModel):
    date: date
    views: int = Field(ge=0)


class StorefrontAnalyticsCountryPoint(BaseModel):
    country_code: str
    views: int = Field(ge=0)
    share: float = Field(ge=0, le=1)


class StorefrontAnalyticsProductPoint(BaseModel):
    product_id: UUID
    sku_id: UUID
    sku_code: str
    name: str
    views: int = Field(ge=0)


class StorefrontAnalyticsCountryProductPoint(BaseModel):
    country_code: str
    sku_id: UUID
    views: int = Field(ge=0)


class StorefrontAnalyticsResponse(BaseModel):
    generated_at: datetime
    timezone: str
    start_date: date
    end_date: date
    days: int = Field(ge=1)
    raw_ip_retention_days: int = Field(ge=1)
    summary: StorefrontAnalyticsSummary
    daily: list[StorefrontAnalyticsDailyPoint]
    countries: list[StorefrontAnalyticsCountryPoint]
    products: list[StorefrontAnalyticsProductPoint]
    country_products: list[StorefrontAnalyticsCountryProductPoint]


class StorefrontProductRankingItem(BaseModel):
    rank: int = Field(ge=1)
    product_id: UUID
    product_code: str | None = None
    name: str
    category_id: UUID | None = None
    category_name: str | None = None
    views: int = Field(ge=0)
    is_pinned: bool = False
    is_popular: bool = False


class StorefrontProductRankingResponse(BaseModel):
    start_date: date
    end_date: date
    days: int = Field(ge=1)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    items: list[StorefrontProductRankingItem]


class PopularCategoryAssignRequest(BaseModel):
    product_ids: list[UUID] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_product_ids(self) -> "PopularCategoryAssignRequest":
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("product ids must be unique")
        return self


class PopularCategoryAssignResponse(BaseModel):
    category_id: UUID
    category_name: str
    selected_count: int = Field(ge=1)
    moved_count: int = Field(ge=0)
    popular_product_count: int = Field(ge=0)
