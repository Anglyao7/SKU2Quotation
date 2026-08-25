from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


CustomerSubaccountCapability = Literal["catalog", "submit_orders", "view_orders"]
CUSTOMER_SUBACCOUNT_CAPABILITIES: tuple[CustomerSubaccountCapability, ...] = (
    "catalog",
    "submit_orders",
    "view_orders",
)


def normalize_capabilities(
    value: list[CustomerSubaccountCapability],
) -> list[CustomerSubaccountCapability]:
    selected = set(value)
    # Every subaccount must retain a usable landing area after login.
    selected.add("catalog")
    return [code for code in CUSTOMER_SUBACCOUNT_CAPABILITIES if code in selected]


class CustomerSubaccountCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    login_identifier: str = Field(min_length=2, max_length=320)
    password: SecretStr
    email: str | None = Field(default=None, max_length=320)
    capabilities: list[CustomerSubaccountCapability] = Field(
        default_factory=lambda: list(CUSTOMER_SUBACCOUNT_CAPABILITIES)
    )

    @field_validator("display_name", "login_identifier", "email", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("login_identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("login identifier is invalid")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and value and "@" not in value:
            raise ValueError("email is invalid")
        return value.lower() if value else None

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        value: list[CustomerSubaccountCapability],
    ) -> list[CustomerSubaccountCapability]:
        return normalize_capabilities(value)


class CustomerSubaccountStatusUpdate(BaseModel):
    status: Literal["active", "suspended"]


class CustomerSubaccountAccessUpdate(BaseModel):
    capabilities: list[CustomerSubaccountCapability]

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(
        cls,
        value: list[CustomerSubaccountCapability],
    ) -> list[CustomerSubaccountCapability]:
        return normalize_capabilities(value)


class CustomerSubaccountSummary(BaseModel):
    id: UUID
    user_id: UUID
    display_name: str
    login_identifier: str
    email: str | None
    status: str
    identity_code: Literal["SUBACCOUNT"] = "SUBACCOUNT"
    capabilities: list[CustomerSubaccountCapability]
    created_at: datetime
    last_login_at: datetime | None
    login_count_30d: int
    order_count: int
    last_order_at: datetime | None
    order_amount: Decimal = Decimal("0")
    today_order_count: int = 0
    today_order_amount: Decimal = Decimal("0")
    month_order_count: int = 0
    month_order_amount: Decimal = Decimal("0")
    markup_percent: Decimal = Decimal("0")
    override_count: int = 0


class CustomerSubaccountOrderSummary(BaseModel):
    id: UUID
    quote_number: str
    status: str
    submitted_by_membership_id: UUID
    submitted_by_name: str
    customer_name: str
    customer_company: str | None
    currency: str
    total_amount: Decimal
    created_at: datetime
    valid_until: datetime


class CustomerSubaccountDashboard(BaseModel):
    accounts: list[CustomerSubaccountSummary]
    active_count: int
    suspended_count: int
    order_count: int
    order_amount: Decimal = Decimal("0")
    today_order_count: int = 0
    today_order_amount: Decimal = Decimal("0")
    month_order_count: int = 0
    month_order_amount: Decimal = Decimal("0")
    currency: str = "CNY"


class SubaccountPricingPolicyResponse(BaseModel):
    membership_id: UUID
    markup_percent: Decimal = Field(ge=0, le=100000)
    override_count: int = Field(ge=0)
    hidden_product_count: int = Field(ge=0)


class SubaccountProductPricingItem(BaseModel):
    product_id: UUID
    product_code: str | None
    product_name: str
    sku_count: int = Field(ge=1)
    base_price_from: Decimal = Field(ge=0)
    base_price_to: Decimal = Field(ge=0)
    effective_price_from: Decimal = Field(ge=0)
    effective_price_to: Decimal = Field(ge=0)
    currency: str
    override_mode: Literal["MARKUP_PERCENT", "FIXED_PRICE"] | None = None
    override_value: Decimal | None = Field(default=None, ge=0)
    updated_at: datetime


class SubaccountPricingPage(BaseModel):
    policy: SubaccountPricingPolicyResponse
    items: list[SubaccountProductPricingItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class SubaccountPricingPolicyUpdate(BaseModel):
    markup_percent: Decimal = Field(ge=0, le=100000)


class SubaccountProductPriceOverrideRequest(BaseModel):
    pricing_mode: Literal["MARKUP_PERCENT", "FIXED_PRICE"]
    value: Decimal = Field(ge=0, le=1000000000000)


class CustomerSubaccountOrderPage(BaseModel):
    """A read-only, paginated view of all direct-child order requests."""

    items: list[CustomerSubaccountOrderSummary]
    total: int
    page: int
    page_size: int


class CustomerPortalOverview(BaseModel):
    display_name: str
    tenant_name: str
    tenant_slug: str
    account_status: str
    order_count: int
    last_order_at: datetime | None


class CustomerPortalOrderSummary(BaseModel):
    id: UUID
    quote_number: str
    status: str
    customer_name: str
    customer_company: str | None
    currency: str
    total_amount: Decimal
    created_at: datetime
    valid_until: datetime
