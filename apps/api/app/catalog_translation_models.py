from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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


class CatalogTranslationOverrideRow(AuditTimestampMixin, Base):
    """Administrator-authored wording that survives automatic retranslation."""

    __tablename__ = "catalog_translation_overrides"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('PRODUCT', 'SKU')",
            name="entity_type_allowed",
        ),
        CheckConstraint(
            "length(source_hash) = 64",
            name="source_hash_sha256_length",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_translation_overrides_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "target_locale",
            "entity_type",
            "entity_id",
            name="uq_catalog_translation_overrides_tenant_locale_entity",
        ),
        Index(
            "ix_catalog_translation_overrides_tenant_locale",
            "tenant_id",
            "target_locale",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    values: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT,
        default=dict,
        nullable=False,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class CatalogLanguagePackRow(AuditTimestampMixin, Base):
    """Currently published immutable storefront language package."""

    __tablename__ = "catalog_language_packs"
    __table_args__ = (
        CheckConstraint(
            "source_locale <> target_locale",
            name="source_target_locale_different",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "length(content_sha256) = 64",
            name="content_sha256_length",
        ),
        CheckConstraint(
            "length(source_digest) = 64",
            name="source_digest_length",
        ),
        CheckConstraint(
            "length(storage_fingerprint) = 64",
            name="storage_fingerprint_length",
        ),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("product_count >= 0", name="product_count_nonnegative"),
        CheckConstraint("sku_count >= 0", name="sku_count_nonnegative"),
        CheckConstraint("category_count >= 0", name="category_count_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_language_packs_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "target_locale",
            name="uq_catalog_language_packs_tenant_locale",
        ),
        Index(
            "ix_catalog_language_packs_tenant_published",
            "tenant_id",
            "published_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    public_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    content_encoding: Mapped[str] = mapped_column(
        String(20), default="gzip", nullable=False
    )
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sku_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_cutoff_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_full_translation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
            "execution_mode IN ('REALTIME', 'QWEN_BATCH')",
            name="execution_mode_allowed",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'PAUSED', 'SUCCEEDED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "stage IN ('QUEUED', 'PREPARING', 'TRANSLATING', 'PACKAGING', "
            "'UPLOADING', 'PAUSED', 'PUBLISHED', 'FAILED')",
            name="stage_allowed",
        ),
        CheckConstraint("total_skus >= 0", name="total_skus_nonnegative"),
        CheckConstraint(
            "processed_skus >= 0 AND processed_skus <= total_skus",
            name="processed_skus_valid",
        ),
        CheckConstraint("failed_skus >= 0", name="failed_skus_nonnegative"),
        CheckConstraint(
            "external_total_requests >= 0 AND "
            "external_completed_requests >= 0 AND "
            "external_failed_requests >= 0",
            name="external_request_counts_nonnegative",
        ),
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
                "status IN ('QUEUED', 'RUNNING', 'PAUSED') AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "status IN ('QUEUED', 'RUNNING', 'PAUSED') AND deleted_at IS NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Platform administrators can run a translation for a merchant without
    # impersonating one of that merchant's memberships. In that case the
    # global user remains the audit actor and this tenant-bound membership is
    # intentionally absent.
    requested_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_mode: Mapped[str] = mapped_column(
        String(30), default="REALTIME", nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    stage: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
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
    remaining_sku_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    forced_sku_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    batch_request_payload: Mapped[dict[str, object]] = mapped_column(
        JSON_DOCUMENT,
        default=dict,
        nullable=False,
    )
    external_input_file_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    external_batch_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    external_output_file_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    external_error_file_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    external_batch_status: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    external_total_requests: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    external_completed_requests: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    external_failed_requests: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    package_published: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    package_byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pause_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CatalogTranslationBatchRow(AuditTimestampMixin, Base):
    """A logical translation request containing a bounded group of SKUs."""

    __tablename__ = "catalog_translation_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint("sequence_no >= 1", name="sequence_positive"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("total_skus >= 0", name="total_skus_nonnegative"),
        CheckConstraint("processed_skus >= 0", name="processed_skus_nonnegative"),
        CheckConstraint("failed_skus >= 0", name="failed_skus_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_translation_batches_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "job_id",
            "sequence_no",
            name="uq_catalog_translation_batches_tenant_job_sequence",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["catalog_translation_jobs.tenant_id", "catalog_translation_jobs.id"],
            name="fk_catalog_translation_batches_tenant_job",
            ondelete="CASCADE",
        ),
        Index(
            "ix_catalog_translation_batches_tenant_job_sequence",
            "tenant_id",
            "job_id",
            "sequence_no",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    sku_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    sku_refs: Mapped[list[dict[str, str]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_byte_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class CatalogTranslationBatchAttemptRow(AuditTimestampMixin, Base):
    """One outbound provider request, including retries of the same batch."""

    __tablename__ = "catalog_translation_batch_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint("attempt_no >= 1", name="attempt_positive"),
        CheckConstraint("processed_skus >= 0", name="processed_skus_nonnegative"),
        CheckConstraint("failed_skus >= 0", name="failed_skus_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_translation_batch_attempts_tenant_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "batch_id",
            "attempt_no",
            name="uq_catalog_translation_batch_attempts_tenant_batch_attempt",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["catalog_translation_batches.tenant_id", "catalog_translation_batches.id"],
            name="fk_catalog_translation_batch_attempts_tenant_batch",
            ondelete="CASCADE",
        ),
        Index(
            "ix_catalog_translation_batch_attempts_tenant_batch_created",
            "tenant_id",
            "batch_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING", nullable=False)
    sku_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    sku_refs: Mapped[list[dict[str, str]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    request_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    first_byte_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
