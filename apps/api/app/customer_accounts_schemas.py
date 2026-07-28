from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


class CustomerSubaccountCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    login_identifier: str = Field(min_length=2, max_length=320)
    password: SecretStr
    email: str | None = Field(default=None, max_length=320)

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


class CustomerSubaccountStatusUpdate(BaseModel):
    status: Literal["active", "suspended"]


class CustomerSubaccountSummary(BaseModel):
    id: UUID
    user_id: UUID
    display_name: str
    login_identifier: str
    email: str | None
    status: str
    created_at: datetime
    last_login_at: datetime | None
    login_count_30d: int
    order_count: int
    last_order_at: datetime | None


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
