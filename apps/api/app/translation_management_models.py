from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin


class TranslationProviderSettingsRow(AuditTimestampMixin, Base):
    """Platform-wide catalog translation provider settings."""

    __tablename__ = "translation_provider_settings"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('openai-compatible', 'aliyun-alimt')",
            name="provider_supported",
        ),
        CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="timeout_supported",
        ),
        CheckConstraint(
            "max_tokens >= 512 AND max_tokens <= 32768",
            name="max_tokens_supported",
        ),
        CheckConstraint(
            "requests_per_minute >= 1 AND requests_per_minute <= 10000",
            name="requests_per_minute_supported",
        ),
        CheckConstraint(
            "max_retry_count >= 0 AND max_retry_count <= 10",
            name="max_retry_count_supported",
        ),
        CheckConstraint(
            "catalog_batch_size >= 1 AND catalog_batch_size <= 200",
            name="catalog_batch_size_supported",
        ),
        CheckConstraint(
            "catalog_batch_characters >= 1000 "
            "AND catalog_batch_characters <= 100000",
            name="catalog_batch_characters_supported",
        ),
        CheckConstraint(
            "reasoning_effort IN ('none', 'minimal', 'low', 'medium', 'high')",
            name="reasoning_effort_supported",
        ),
        CheckConstraint(
            "is_active = false OR ("
            "api_key_ciphertext IS NOT NULL AND ("
            "provider = 'openai-compatible' OR "
            "access_key_id_ciphertext IS NOT NULL))",
            name="active_key_required",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(40), default="openai-compatible", nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    region_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=16384, nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )
    max_retry_count: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    catalog_batch_size: Mapped[int] = mapped_column(
        Integer,
        default=50,
        nullable=False,
    )
    catalog_batch_characters: Mapped[int] = mapped_column(
        Integer,
        default=10_000,
        nullable=False,
    )
    reasoning_effort: Mapped[str] = mapped_column(
        String(20), default="low", nullable=False
    )
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    access_key_id_ciphertext: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    access_key_id_last_four: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
