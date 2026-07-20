from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditTimestampMixin:
    """Common lifecycle fields for mutable core and association records."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def mark_deleted(record: AuditTimestampMixin, *, at: datetime | None = None) -> None:
    timestamp = at or utcnow()
    record.deleted_at = timestamp
    record.updated_at = timestamp


def restore_deleted(record: AuditTimestampMixin, *, at: datetime | None = None) -> None:
    record.deleted_at = None
    record.updated_at = at or utcnow()
