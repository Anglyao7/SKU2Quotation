from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin, utcnow


class StorefrontVisitEventRow(AuditTimestampMixin, Base):
    """A privacy-preserving storefront visit marker.

    The visitor key is a one-way digest of the request IP.  It is used only to
    deduplicate visitors inside an aggregate window and is never returned by
    the platform monitoring API.
    """

    __tablename__ = "storefront_visit_events"
    __table_args__ = (
        CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code)",
            name="country_code_format",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_visit_events_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            name="uq_storefront_visit_events_event",
        ),
        Index(
            "ix_storefront_visit_events_tenant_occurred",
            "tenant_id",
            "occurred_at",
        ),
        Index(
            "ix_storefront_visit_events_tenant_visitor_occurred",
            "tenant_id",
            "visitor_key",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    visitor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2), default="ZZ", nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class TenantUsageDailyRow(AuditTimestampMixin, Base):
    """Small counters for public events that have no durable business row."""

    __tablename__ = "tenant_usage_daily"
    __table_args__ = (
        CheckConstraint(
            "image_search_count >= 0",
            name="image_search_count_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "usage_date",
            name="uq_tenant_usage_daily_tenant_date",
        ),
        Index(
            "ix_tenant_usage_daily_tenant_date",
            "tenant_id",
            "usage_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    image_search_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
