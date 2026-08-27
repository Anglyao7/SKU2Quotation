from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator

from .tenant_slugs import is_reserved_tenant_slug
from .tenant_modules import (
    DEFAULT_MERCHANT_IDENTITY,
    DEFAULT_TENANT_MODULE_ACCESS_MODE,
    MerchantIdentityCode,
    TenantModuleCode,
    TenantModuleAccessMode,
    canonical_tenant_module_list,
    default_tenant_modules,
)
from .tenant_subscriptions import (
    TenantSubscriptionStatus,
    TenantSubscriptionTier,
)


TenantStatus = Literal["active", "suspended", "archived"]
TenantRoleCode = Literal["OWNER", "ADMIN", "SALES", "PURCHASING", "VIEWER"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PlatformMerchantOwnerCreate(BaseModel):
    """Credentials for the first, full-access account of a merchant."""

    display_name: str = Field(min_length=1, max_length=120)
    login_identifier: str = Field(min_length=2, max_length=320)
    password: SecretStr
    email: str | None = Field(default=None, max_length=320)

    @field_validator("display_name", "login_identifier", "email", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("login_identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Login account is invalid.")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None or not value:
            return None
        normalized = value.lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class PlatformMerchantOwnerAccount(BaseModel):
    user_id: UUID
    membership_id: UUID
    display_name: str
    login_identifier: str | None
    email: str | None
    status: Literal["active", "invited", "suspended", "removed"]
    created_at: datetime


class PlatformMerchantOwnerPasswordReset(BaseModel):
    """A new password supplied by a platform administrator."""

    password: SecretStr


class PlatformMerchantOwnerPasswordResetResponse(BaseModel):
    """Password is returned only in the reset response, never in listings."""

    account: PlatformMerchantOwnerAccount
    one_time_password: str


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
    identity_code: MerchantIdentityCode
    module_access_mode: TenantModuleAccessMode
    enabled_modules: list[TenantModuleCode]
    module_overrides: list[TenantModuleCode] | None = None
    subscription_tier: TenantSubscriptionTier
    subscription_started_at: datetime
    subscription_expires_at: datetime
    subscription_status: TenantSubscriptionStatus
    sku_limit: int | None = Field(default=None, ge=0)
    sku_remaining: int | None = Field(default=None, ge=0)
    contact_email: str | None
    sku_count: int = Field(ge=0)
    quote_count: int = Field(ge=0)
    owner_account: PlatformMerchantOwnerAccount | None = None
    created_at: datetime
    updated_at: datetime


class PlatformMerchantDailyMetric(BaseModel):
    date: date
    count: int = Field(ge=0)


class PlatformMerchantStatusMetric(BaseModel):
    status: Literal[
        "PENDING_CONFIRMATION",
        "CONFIRMED",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
    ]
    count: int = Field(ge=0)


class PlatformMerchantMonitoring(BaseModel):
    generated_at: datetime
    period_days: int = Field(default=30, ge=1)
    quotes_total: int = Field(ge=0)
    quotes_period: int = Field(ge=0)
    quotes_pending: int = Field(ge=0)
    quotes_confirmed: int = Field(ge=0)
    quotes_completed: int = Field(ge=0)
    quotes_cancelled: int = Field(ge=0)
    skus_total: int = Field(ge=0)
    subaccounts_total: int = Field(ge=0)
    subaccounts_active: int = Field(ge=0)
    storefront_visitors_period: int = Field(ge=0)
    product_views_period: int = Field(ge=0)
    last_quote_at: datetime | None = None
    quote_statuses: list[PlatformMerchantStatusMetric]
    quote_trend: list[PlatformMerchantDailyMetric]
    product_view_trend: list[PlatformMerchantDailyMetric]


class PlatformMerchantSubaccountSummary(BaseModel):
    id: UUID
    user_id: UUID
    display_name: str
    login_identifier: str
    email: str | None
    status: Literal["invited", "active", "suspended"]
    # Kept alongside the legacy capability projection for older clients.  A
    # child account is an operator of the merchant workspace, so the platform
    # view should describe the actual workspace modules that the parent has
    # opened rather than presenting it as a public guest account.
    modules: list[Literal["products", "inquiries", "quotations", "announcements", "support"]] = Field(
        default_factory=lambda: [
            "products",
            "inquiries",
            "quotations",
            "announcements",
            "support",
        ]
    )
    capabilities: list[Literal["catalog", "submit_orders", "view_orders"]]
    parent_membership_id: UUID | None = None
    parent_display_name: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None
    login_count_30d: int = Field(ge=0)
    quote_count: int = Field(ge=0)
    last_quote_at: datetime | None = None


class PlatformMerchantRecentQuote(BaseModel):
    id: UUID
    quote_number: str
    status: Literal[
        "PENDING_CONFIRMATION",
        "CONFIRMED",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
    ]
    customer_name: str
    customer_company: str | None = None
    currency: str
    total_amount: Decimal = Field(ge=0)
    created_at: datetime
    valid_until: datetime


class PlatformTenantDetail(BaseModel):
    merchant: PlatformTenantSummary
    monitoring: PlatformMerchantMonitoring
    subaccounts: list[PlatformMerchantSubaccountSummary]


class PlatformMerchantSubaccountDetail(BaseModel):
    merchant: PlatformTenantSummary
    account: PlatformMerchantSubaccountSummary
    recent_quotes: list[PlatformMerchantRecentQuote]


class PlatformTenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9](?:[a-z0-9-]{1,78})[a-z0-9]$",
    )
    contact_email: str | None = Field(default=None, max_length=320)
    active: bool = True
    default_locale: str = Field(default="zh-CN", min_length=2, max_length=20)
    default_currency: str = Field(default="CNY", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    identity_code: MerchantIdentityCode = Field(
        default=DEFAULT_MERCHANT_IDENTITY,
        min_length=1,
        max_length=20,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    module_access_mode: TenantModuleAccessMode = DEFAULT_TENANT_MODULE_ACCESS_MODE
    enabled_modules: list[TenantModuleCode] = Field(default_factory=default_tenant_modules)

    @field_validator("name", "slug", "contact_email", "default_locale", "timezone", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("slug")
    @classmethod
    def reject_reserved_storefront_slug(cls, value: str | None) -> str | None:
        if value is not None and is_reserved_tenant_slug(value):
            raise ValueError("This storefront slug is reserved by the platform.")
        return value

    @field_validator("default_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("identity_code", "module_access_mode", mode="before")
    @classmethod
    def normalize_access_value(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("enabled_modules")
    @classmethod
    def normalize_modules(
        cls,
        value: list[TenantModuleCode],
    ) -> list[TenantModuleCode]:
        return canonical_tenant_module_list(value)


class PlatformTenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    active: bool | None = None
    default_locale: str | None = Field(default=None, min_length=2, max_length=20)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    identity_code: MerchantIdentityCode | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    module_access_mode: TenantModuleAccessMode | None = None
    enabled_modules: list[TenantModuleCode] | None = None

    @field_validator("name", "contact_email", "default_locale", "timezone", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("default_currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("identity_code", "module_access_mode", mode="before")
    @classmethod
    def normalize_access_value(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("enabled_modules")
    @classmethod
    def normalize_modules(
        cls,
        value: list[TenantModuleCode] | None,
    ) -> list[TenantModuleCode] | None:
        return None if value is None else canonical_tenant_module_list(value)


class PlatformMerchantIdentityProfile(BaseModel):
    code: MerchantIdentityCode
    name: str
    enabled_modules: list[TenantModuleCode]
    is_system: bool
    editable: bool
    version: int = Field(ge=1)
    updated_at: datetime


class PlatformMerchantIdentityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled_modules: list[TenantModuleCode] = Field(default_factory=default_tenant_modules)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("enabled_modules")
    @classmethod
    def normalize_modules(
        cls,
        value: list[TenantModuleCode],
    ) -> list[TenantModuleCode]:
        return canonical_tenant_module_list(value)


class PlatformMerchantIdentityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled_modules: list[TenantModuleCode] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("enabled_modules")
    @classmethod
    def normalize_modules(
        cls,
        value: list[TenantModuleCode] | None,
    ) -> list[TenantModuleCode] | None:
        return None if value is None else canonical_tenant_module_list(value)


class PlatformTenantSubscriptionUpdate(BaseModel):
    subscription_tier: TenantSubscriptionTier
    subscription_expires_at: datetime
    sku_limit: int | None = Field(default=None, ge=0)

    @field_validator("subscription_tier", mode="before")
    @classmethod
    def normalize_tier(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("subscription_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Subscription expiry must include a timezone.")
        return value


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
