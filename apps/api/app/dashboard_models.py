from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class DashboardStatisticsRow(AuditTimestampMixin, Base):
    """Tenant-level dashboard read model.

    The overview is intentionally served from this row instead of counting
    the product and trade-flow tables on every page load.  ``is_dirty`` is
    flipped by the write-session cache hook and the row is rebuilt lazily on
    the next dashboard request.  The small membership map keeps restricted
    sub-accounts from seeing tenant-wide inquiry totals while avoiding a
    separate count query for every dashboard visit.
    """

    __tablename__ = "dashboard_statistics"
    __table_args__ = (
        CheckConstraint("active_skus >= 0", name="active_skus_nonnegative"),
        CheckConstraint("active_products >= 0", name="active_products_nonnegative"),
        CheckConstraint("active_suppliers >= 0", name="active_suppliers_nonnegative"),
        CheckConstraint("today_inquiries >= 0", name="today_inquiries_nonnegative"),
        CheckConstraint("open_inquiries >= 0", name="open_inquiries_nonnegative"),
        CheckConstraint("pending_quotes >= 0", name="pending_quotes_nonnegative"),
        CheckConstraint("pending_reviews >= 0", name="pending_reviews_nonnegative"),
        CheckConstraint("approved_images >= 0", name="approved_images_nonnegative"),
        CheckConstraint("sourced_products >= 0", name="sourced_products_nonnegative"),
        CheckConstraint("priced_products >= 0", name="priced_products_nonnegative"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    statistics_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_dirty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active_skus: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    active_products: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    active_suppliers: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    today_inquiries: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    open_inquiries: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pending_quotes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    pending_reviews: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    approved_images: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sourced_products: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    priced_products: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    membership_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        default=dict,
        nullable=False,
    )
