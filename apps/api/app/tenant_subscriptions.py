from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Literal


TenantSubscriptionTier = Literal["TRIAL", "STANDARD", "SILVER", "ELITE"]
TenantSubscriptionStatus = Literal["active", "expiring_soon", "expired"]

TENANT_SUBSCRIPTION_TIERS: tuple[TenantSubscriptionTier, ...] = (
    "TRIAL",
    "STANDARD",
    "SILVER",
    "ELITE",
)

DEFAULT_SKU_LIMITS: dict[TenantSubscriptionTier, int | None] = {
    "TRIAL": 500,
    "STANDARD": 5_000,
    "SILVER": 5_000,
    "ELITE": None,
}


def default_sku_limit(tier: TenantSubscriptionTier) -> int | None:
    return DEFAULT_SKU_LIMITS[tier]


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Add calendar months while keeping end-of-month dates valid."""

    if months < 1:
        raise ValueError("months must be positive")
    target_index = value.month - 1 + months
    year = value.year + target_index // 12
    month = target_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def default_subscription_expiry(
    tier: TenantSubscriptionTier,
    *,
    started_at: datetime,
) -> datetime:
    return add_calendar_months(started_at, 1 if tier == "TRIAL" else 12)


def normalized_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def subscription_status(
    expires_at: datetime,
    *,
    now: datetime,
) -> TenantSubscriptionStatus:
    remaining_seconds = (normalized_utc(expires_at) - normalized_utc(now)).total_seconds()
    if remaining_seconds <= 0:
        return "expired"
    if remaining_seconds <= 14 * 24 * 60 * 60:
        return "expiring_soon"
    return "active"
