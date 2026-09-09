"""Durable, opt-in automatic translation state scoped to a merchant."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base


class CatalogTranslationChangeRow(Base):
    __tablename__ = "catalog_translation_changes"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogTranslationAutomationTenantRow(Base):
    """Merchant-level switch for automatic catalog translation.

    Language rows below retain per-language runtime state (last job, baseline,
    and publication preferences), but this row is the only source of truth for
    whether automatic updates are enabled for the merchant.
    """

    __tablename__ = "catalog_translation_automation_tenants"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogTranslationAutomationRow(Base):
    __tablename__ = "catalog_translation_automation"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    target_locale: Mapped[str] = mapped_column(String(20), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    debounce_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    approved_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    observed_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Text-only fingerprints. Product/SKU version changes do not invalidate them.
    observed_sources: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_job_id: Mapped[UUID | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
