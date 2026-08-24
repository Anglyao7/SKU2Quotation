from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..subaccount_pricing_models import (
    SubaccountPricingPolicyRow,
    SubaccountProductPriceOverrideRow,
)


MONEY = Decimal("0.01")


def subaccount_price_rules(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID | None,
    product_ids: set[UUID],
) -> tuple[Decimal, dict[UUID, SubaccountProductPriceOverrideRow], set[UUID]]:
    """Load one child account's pricing rules for a bounded catalog page."""

    if membership_id is None or not product_ids:
        return Decimal("0"), {}, set()
    policy = session.scalar(
        select(SubaccountPricingPolicyRow).where(
            SubaccountPricingPolicyRow.tenant_id == tenant_id,
            SubaccountPricingPolicyRow.membership_id == membership_id,
            SubaccountPricingPolicyRow.deleted_at.is_(None),
        )
    )
    if policy is None:
        return Decimal("0"), {}, set()
    overrides = {
        row.product_id: row
        for row in session.scalars(
            select(SubaccountProductPriceOverrideRow).where(
                SubaccountProductPriceOverrideRow.tenant_id == tenant_id,
                SubaccountProductPriceOverrideRow.membership_id == membership_id,
                SubaccountProductPriceOverrideRow.product_id.in_(product_ids),
                SubaccountProductPriceOverrideRow.is_active.is_(True),
                SubaccountProductPriceOverrideRow.deleted_at.is_(None),
            )
        ).all()
    }
    hidden = {
        UUID(str(value))
        for value in (policy.hidden_product_ids or [])
        if _is_uuid(value)
    }
    return Decimal(policy.markup_percent), overrides, hidden


def effective_subaccount_price(
    base_price: Decimal,
    *,
    markup_percent: Decimal,
    override: SubaccountProductPriceOverrideRow | None,
) -> Decimal:
    if override is not None and override.is_active:
        if override.pricing_mode == "FIXED_PRICE":
            return Decimal(override.value).quantize(MONEY, rounding=ROUND_HALF_UP)
        markup_percent = Decimal(override.value)
    return (
        Decimal(base_price)
        * (Decimal("1") + Decimal(markup_percent) / Decimal("100"))
    ).quantize(MONEY, rounding=ROUND_HALF_UP)


def _is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False
