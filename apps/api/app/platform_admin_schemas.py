from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .tenant_slugs import is_reserved_tenant_slug


TenantStatus = Literal["active", "suspended", "archived"]
TenantRoleCode = Literal["OWNER", "ADMIN", "SALES", "PURCHASING", "VIEWER"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

    @field_validator("slug")
    @classmethod
    def reject_reserved_storefront_slug(cls, value: str) -> str:
        if is_reserved_tenant_slug(value):
            raise ValueError("This storefront slug is reserved by the platform.")
        return value

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


class PlatformMemberInvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    role: TenantRoleCode

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class PlatformMemberInvitation(BaseModel):
    tenant_id: UUID
    user_id: UUID
    membership_id: UUID
    email: str
    display_name: str
    role: TenantRoleCode
    membership_status: Literal["invited", "active"]
    created: bool
    identity_already_bound: bool
    requires_identity_provider_provisioning: bool
