from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class CatalogSkuTranslationRow(AuditTimestampMixin, Base):
    """Cached public-catalog content translated outside the request path."""

    __tablename__ = "catalog_sku_translations"
    __table_args__ = (
        CheckConstraint(
            "source_locale <> target_locale",
            name="source_target_locale_different",
        ),
        CheckConstraint(
            "length(source_hash) = 64",
            name="source_hash_sha256_length",
        ),
        CheckConstraint("product_version >= 1", name="product_version_positive"),
        CheckConstraint("sku_version >= 1", name="sku_version_positive"),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_sku_translations_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "sku_id",
            "target_locale",
            name="uq_catalog_sku_translations_tenant_sku_locale",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_catalog_sku_translations_tenant_sku",
            ondelete="CASCADE",
        ),
        Index(
            "ix_catalog_sku_translations_tenant_locale",
            "tenant_id",
            "target_locale",
        ),
        Index(
            "ix_catalog_sku_translations_tenant_category_locale",
            "tenant_id",
            "source_category",
            "target_locale",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    source_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_category: Mapped[str | None] = mapped_column(String(300), nullable=True)
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    display_tag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(120), nullable=False)
    product_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sku_version: Mapped[int] = mapped_column(Integer, nullable=False)


class CatalogTextTranslationRow(AuditTimestampMixin, Base):
    """On-demand translation memory shared by catalog fields with equal text."""

    __tablename__ = "catalog_text_translations"
    __table_args__ = (
        CheckConstraint(
            "source_locale <> target_locale",
            name="source_target_locale_different",
        ),
        CheckConstraint(
            "length(source_hash) = 64",
            name="source_hash_sha256_length",
        ),
        UniqueConstraint(
            "tenant_id",
            "source_locale",
            "target_locale",
            "provider",
            "provider_version",
            "source_hash",
            name="uq_catalog_text_translations_memory_key",
        ),
        Index(
            "ix_catalog_text_translations_tenant_accessed",
            "tenant_id",
            "last_accessed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(120), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class CatalogTranslationJobRow(AuditTimestampMixin, Base):
    """Tenant-scoped progress record for an explicit catalog translation run."""

    __tablename__ = "catalog_translation_jobs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('INCREMENTAL', 'FULL_REBUILD')",
            name="mode_allowed",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("total_skus >= 0", name="total_skus_nonnegative"),
        CheckConstraint(
            "processed_skus >= 0 AND processed_skus <= total_skus",
            name="processed_skus_valid",
        ),
        CheckConstraint("failed_skus >= 0", name="failed_skus_nonnegative"),
        CheckConstraint(
            "source_locale <> target_locale",
            name="source_target_locale_different",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_translation_jobs_tenant_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_catalog_translation_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_catalog_translation_jobs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "uq_catalog_translation_jobs_active_tenant_locale",
            "tenant_id",
            "target_locale",
            unique=True,
            postgresql_where=text(
                "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    total_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_sku_id: Mapped[UUID | None] = mapped_column(nullable=True)
    current_sku_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(120), nullable=False)
    failure_details: Mapped[list[dict[str, str]]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
