from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


TenantStatus = Literal["active", "suspended", "archived"]


class PlatformTenantSummary(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    status: TenantStatus
    active: bool
    default_locale: str
    default_currency: str
    timezone: str
    contact_email: str | None
    sku_count: int = Field(ge=0)
    quote_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class PlatformTenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{1,78})[a-z0-9]$")
    contact_email: str | None = Field(default=None, max_length=320)
    active: bool = True
    default_locale: str = Field(default="zh-CN", min_length=2, max_length=20)
    default_currency: str = Field(default="CNY", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)

    @field_validator("name", "slug", "contact_email", "default_locale", "timezone", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("default_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class PlatformTenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    active: bool | None = None

    @field_validator("name", "contact_email", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value
