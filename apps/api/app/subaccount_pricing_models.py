from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class SubaccountPricingPolicyRow(AuditTimestampMixin, Base):
    """Price policy owned by a merchant's direct child account.

    The tenant's published offer remains the source price.  A child account
    receives that price multiplied by ``1 + markup_percent / 100`` unless a
    product override is present.  Keeping this in a separate table makes the
    policy auditable and prevents reseller prices from leaking into the main
    catalog offer.
    """

    __tablename__ = "subaccount_pricing_policies"
    __table_args__ = (
        CheckConstraint("markup_percent >= 0", name="markup_percent_nonnegative"),
        CheckConstraint("markup_percent <= 100000", name="markup_percent_reasonable"),
        UniqueConstraint("tenant_id", "membership_id", name="uq_subaccount_pricing_policy_membership"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_subaccount_pricing_policy_membership",
            ondelete="CASCADE",
        ),
        Index("ix_subaccount_pricing_policies_tenant_membership", "tenant_id", "membership_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    markup_percent: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("0"), nullable=False
    )
    # Product ids explicitly hidden from this child account.  This is kept as
    # a small policy projection for the first version; price overrides remain
    # normalized in ``subaccount_product_price_overrides``.
    hidden_product_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )


class SubaccountProductPriceOverrideRow(AuditTimestampMixin, Base):
    """An optional per-product reseller price rule."""

    __tablename__ = "subaccount_product_price_overrides"
    __table_args__ = (
        CheckConstraint(
            "pricing_mode IN ('MARKUP_PERCENT', 'FIXED_PRICE')",
            name="pricing_mode_allowed",
        ),
        CheckConstraint("value >= 0", name="override_value_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "membership_id",
            "product_id",
            name="uq_subaccount_product_price_override",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_subaccount_product_price_override_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_subaccount_product_price_override_product",
            ondelete="CASCADE",
        ),
        Index(
            "ix_subaccount_product_price_overrides_tenant_membership",
            "tenant_id",
            "membership_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    pricing_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
