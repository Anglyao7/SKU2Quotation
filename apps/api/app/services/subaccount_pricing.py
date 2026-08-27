from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..subaccount_pricing_models import (
    SubaccountCategoryPriceOverrideRow,
    SubaccountPricingPolicyRow,
    SubaccountProductPriceOverrideRow,
    SubaccountSkuPriceOverrideRow,
)
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductCategoryRow


MONEY = Decimal("0.01")


def subaccount_price_rules(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID | None,
    product_ids: set[UUID],
) -> tuple[Decimal, dict[UUID, SubaccountProductPriceOverrideRow], set[UUID]]:
    """Load one child account's pricing rules for a bounded catalog page."""

    if membership_id is None:
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
    if not product_ids:
        # Callers that only need visibility (for example a paginated catalog
        # query) still need the policy projection even when they have not
        # loaded a page of products yet.
        return Decimal(policy.markup_percent), {}, hidden
    return Decimal(policy.markup_percent), overrides, hidden


def effective_subaccount_price(
    base_price: Decimal,
    *,
    markup_percent: Decimal,
    override: SubaccountProductPriceOverrideRow | None,
    category_markup_percent: Decimal | None = None,
    sku_override: SubaccountSkuPriceOverrideRow | None = None,
) -> Decimal:
    # Rules are intentionally most-specific-first.  A fixed SKU price is an
    # explicit exception; a percentage SKU rule still preserves the source
    # price differences between variants.
    for candidate in (sku_override, override):
        if candidate is None or not candidate.is_active:
            continue
        if candidate.pricing_mode == "FIXED_PRICE":
            return Decimal(candidate.value).quantize(MONEY, rounding=ROUND_HALF_UP)
        markup_percent = Decimal(candidate.value)
        break
    else:
        if category_markup_percent is not None:
            markup_percent = Decimal(category_markup_percent)
    return (
        Decimal(base_price)
        * (Decimal("1") + Decimal(markup_percent) / Decimal("100"))
    ).quantize(MONEY, rounding=ROUND_HALF_UP)


def subaccount_sku_price_rules(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID | None,
    sku_ids: set[UUID] | None = None,
    product_ids: set[UUID] | None = None,
) -> dict[UUID, SubaccountSkuPriceOverrideRow]:
    """Load active SKU-specific rules in one query.

    ``product_ids`` is a convenience for product-card pages that do not have
    SKU rows in hand yet.  It is resolved to SKU ids in SQL and therefore does
    not introduce an N+1 query pattern.
    """

    if membership_id is None:
        return {}
    requested_sku_ids = set(sku_ids or set())
    if not requested_sku_ids and product_ids:
        requested_sku_ids = set(
            session.scalars(
                select(SkuRow.id).where(
                    SkuRow.tenant_id == tenant_id,
                    SkuRow.product_id.in_(product_ids),
                    SkuRow.deleted_at.is_(None),
                )
            ).all()
        )
    if not requested_sku_ids:
        return {}
    return {
        row.sku_id: row
        for row in session.scalars(
            select(SubaccountSkuPriceOverrideRow).where(
                SubaccountSkuPriceOverrideRow.tenant_id == tenant_id,
                SubaccountSkuPriceOverrideRow.membership_id == membership_id,
                SubaccountSkuPriceOverrideRow.sku_id.in_(requested_sku_ids),
                SubaccountSkuPriceOverrideRow.is_active.is_(True),
                SubaccountSkuPriceOverrideRow.deleted_at.is_(None),
            )
        ).all()
    }


def subaccount_category_price_rules(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID | None,
    category_ids: set[UUID],
) -> dict[UUID, Decimal]:
    """Return the most specific category markup for each requested category.

    Categories are currently at most two levels deep.  The parent fallback is
    still resolved from the table rather than encoded in the UI, so imports and
    future category reordering keep the pricing rule correct.
    """

    if membership_id is None or not category_ids:
        return {}
    categories = list(
        session.scalars(
            select(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.id.in_(category_ids),
                ProductCategoryRow.deleted_at.is_(None),
            )
        ).all()
    )
    parent_ids = {
        category.parent_id
        for category in categories
        if category.parent_id is not None
    }
    if parent_ids:
        categories.extend(
            session.scalars(
                select(ProductCategoryRow).where(
                    ProductCategoryRow.tenant_id == tenant_id,
                    ProductCategoryRow.id.in_(parent_ids),
                    ProductCategoryRow.deleted_at.is_(None),
                )
            ).all()
        )
    rules = {
        row.category_id: Decimal(row.markup_percent)
        for row in session.scalars(
            select(SubaccountCategoryPriceOverrideRow).where(
                SubaccountCategoryPriceOverrideRow.tenant_id == tenant_id,
                SubaccountCategoryPriceOverrideRow.membership_id == membership_id,
                SubaccountCategoryPriceOverrideRow.is_active.is_(True),
                SubaccountCategoryPriceOverrideRow.deleted_at.is_(None),
            )
        ).all()
    }
    by_id = {category.id: category for category in categories}
    resolved: dict[UUID, Decimal] = {}
    for category_id in category_ids:
        if category_id in rules:
            resolved[category_id] = rules[category_id]
            continue
        parent_id = getattr(by_id.get(category_id), "parent_id", None)
        if parent_id in rules:
            resolved[category_id] = rules[parent_id]
    return resolved


def _is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False
