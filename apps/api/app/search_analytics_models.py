from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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


class StorefrontSearchTermDailyRow(AuditTimestampMixin, Base):
    """Tenant-scoped daily aggregate for public catalog search terms.

    Keeping one row per tenant, UTC day, and normalized term avoids storing
    visitor IPs or a high-cardinality event stream while still allowing the
    management console to rank terms over a selectable time window.
    """

    __tablename__ = "storefront_search_term_daily"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_search_term_daily_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "searched_on",
            "term_normalized",
            name="uq_storefront_search_term_daily_term",
        ),
        Index(
            "ix_storefront_search_term_daily_tenant_date",
            "tenant_id",
            "searched_on",
        ),
        Index(
            "ix_storefront_search_term_daily_tenant_count",
            "tenant_id",
            "search_count",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    searched_on: Mapped[date] = mapped_column(Date, nullable=False)
    term_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    term_display: Mapped[str] = mapped_column(String(200), nullable=False)
    search_count: Mapped[int] = mapped_column(
        BigInteger, default=1, server_default="1", nullable=False
    )
    last_searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
