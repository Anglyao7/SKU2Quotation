from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_STOREFRONT_CUSTOM_PAGES = 12
MAX_STOREFRONT_HTML_BYTES = 2 * 1024 * 1024
STOREFRONT_PAGE_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_storefront_page_slug(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if not STOREFRONT_PAGE_SLUG_PATTERN.fullmatch(normalized):
        raise ValueError("route slug must contain lowercase letters, numbers, or hyphens")
    return normalized


class StorefrontCustomPageResponse(BaseModel):
    id: UUID
    title: str
    slug: str
    path: str
    enabled: bool
    exchange_rates_enabled: bool
    sort_order: int
    original_filename: str
    byte_size: int
    content_sha256: str
    version: int
    created_at: datetime
    updated_at: datetime


class StorefrontCustomPageListResponse(BaseModel):
    items: list[StorefrontCustomPageResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    max_pages: int = MAX_STOREFRONT_CUSTOM_PAGES


class StorefrontCustomPageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    slug: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    exchange_rates_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    expected_version: int = Field(ge=1)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: object) -> object:
        if value is None:
            return None
        return normalize_storefront_page_slug(value)

    @model_validator(mode="after")
    def require_change(self) -> StorefrontCustomPageUpdate:
        if (
            self.title is None
            and self.slug is None
            and self.enabled is None
            and self.exchange_rates_enabled is None
            and self.sort_order is None
        ):
            raise ValueError("at least one page setting is required")
        return self


class PublicStorefrontPageLink(BaseModel):
    title: str
    slug: str
    path: str
    exchange_rates_enabled: bool = False


class PublicStorefrontPageDocument(BaseModel):
    title: str
    slug: str
    exchange_rates_enabled: bool = False
    html: str
    content_sha256: str
    updated_at: datetime
