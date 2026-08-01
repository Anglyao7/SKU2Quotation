from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class StorefrontAnnouncementRow(AuditTimestampMixin, Base):
    """Tenant-owned, scheduled content displayed on the public storefront."""

    __tablename__ = "storefront_announcements"
    __table_args__ = (
        CheckConstraint(
            "display_type IN ('TICKER', 'MODAL')",
            name="display_type_allowed",
        ),
        CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'PAUSED')",
            name="publication_status_allowed",
        ),
        CheckConstraint("ends_at > starts_at", name="schedule_range_valid"),
        CheckConstraint(
            "ticker_speed_px_per_second BETWEEN 20 AND 160",
            name="ticker_speed_px_per_second_valid",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(display_type = 'TICKER' AND ticker_text IS NOT NULL) "
            "OR (display_type = 'MODAL' AND ticker_text IS NULL)",
            name="display_content_matches_type",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_announcements_tenant_identity",
        ),
        Index(
            "ix_storefront_announcements_tenant_schedule",
            "tenant_id",
            "publication_status",
            "starts_at",
            "ends_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ticker_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_blocks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    related_sku_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ticker_speed_px_per_second: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )
    publication_status: Mapped[str] = mapped_column(
        String(20),
        default="DRAFT",
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        BigInteger,
        default=1,
        nullable=False,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
