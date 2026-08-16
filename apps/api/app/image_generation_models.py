from __future__ import annotations

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin


class ImageGenerationProviderSettingsRow(AuditTimestampMixin, Base):
    """Platform-managed image-to-image provider configuration."""

    __tablename__ = "image_generation_provider_settings"
    __table_args__ = (
        CheckConstraint(
            "provider = 'agnes-ai'",
            name="provider_supported",
        ),
        CheckConstraint(
            "timeout_seconds >= 60 AND timeout_seconds <= 360",
            name="timeout_supported",
        ),
        CheckConstraint(
            "requests_per_minute >= 1 AND requests_per_minute <= 10000",
            name="requests_per_minute_supported",
        ),
        CheckConstraint(
            "concurrency_limit >= 1 AND concurrency_limit <= 32",
            name="concurrency_supported",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(40), default="agnes-ai", nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=180, nullable=False
    )
    requests_per_minute: Mapped[int] = mapped_column(
        Integer, default=6, nullable=False
    )
    concurrency_limit: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False
    )
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
