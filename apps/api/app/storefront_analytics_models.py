from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import utcnow


class StorefrontProductViewEventRow(Base):
    """Append-only detail-page view with the original, normalized client IP."""

    __tablename__ = "storefront_product_view_events"
    __table_args__ = (
        CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code)",
            name="country_code_format",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_product_view_events_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            name="uq_storefront_product_view_events_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_storefront_product_view_events_tenant_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_storefront_product_view_events_tenant_sku",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_storefront_product_view_events_tenant_occurred",
            "tenant_id",
            "occurred_at",
        ),
        Index(
            "ix_storefront_product_view_events_tenant_sku_occurred",
            "tenant_id",
            "sku_id",
            "occurred_at",
        ),
        Index(
            "ix_storefront_product_view_events_tenant_country_occurred",
            "tenant_id",
            "country_code",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_code_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2), default="ZZ", nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class StorefrontProductViewDailyRow(Base):
    """Small permanent aggregate used by merchant-facing ECharts dashboards."""

    __tablename__ = "storefront_product_view_daily"
    __table_args__ = (
        CheckConstraint("view_count >= 1", name="view_count_positive"),
        CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code)",
            name="country_code_format",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_product_view_daily_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "viewed_on",
            "country_code",
            "sku_id",
            name="uq_storefront_product_view_daily_bucket",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_storefront_product_view_daily_tenant_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_storefront_product_view_daily_tenant_sku",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_storefront_product_view_daily_tenant_date",
            "tenant_id",
            "viewed_on",
        ),
        Index(
            "ix_storefront_product_view_daily_tenant_product_date",
            "tenant_id",
            "product_id",
            "viewed_on",
        ),
        Index(
            "ix_storefront_product_view_daily_tenant_country_date",
            "tenant_id",
            "country_code",
            "viewed_on",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    viewed_on: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_code_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2), default="ZZ", nullable=False
    )
    view_count: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
