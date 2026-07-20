from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from .database import Base
from .model_mixins import AuditTimestampMixin


JSON_DOCUMENT = JSON().with_variant(JSONB(none_as_null=True), "postgresql")


class MediaObjectRow(AuditTimestampMixin, Base):
    __tablename__ = "media_objects"
    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint(
            "zone IN ('QUARANTINE', 'SOURCE', 'DERIVED', 'APPROVED_MEDIA', "
            "'DOCUMENT', 'LEGAL_HOLD')",
            name="zone_allowed",
        ),
        CheckConstraint(
            "status IN ('UPLOADING', 'QUARANTINED', 'SCANNING', 'AVAILABLE', "
            "'REJECTED', 'DELETED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "scan_status IN ('PENDING', 'RUNNING', 'CLEAN', 'INFECTED', 'ERROR')",
            name="scan_status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_media_objects_tenant_identity"),
        UniqueConstraint("tenant_id", "object_key", name="uq_media_objects_tenant_object_key"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_media_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_media_objects_tenant_parent",
            ondelete="RESTRICT",
        ),
        Index("ix_media_objects_tenant_sha256", "tenant_id", "sha256"),
        Index(
            "ix_media_objects_tenant_scan_status",
            "tenant_id",
            "scan_status",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    zone: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARANTINE")
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_media_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detected_media_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARANTINED")
    scan_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    scan_engine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scan_result: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_media_id: Mapped[UUID | None] = mapped_column(nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(40), nullable=False, default="SOURCE_DEFAULT"
    )
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class WorkerJobRow(AuditTimestampMixin, Base):
    __tablename__ = "worker_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'RETRY', 'SUCCEEDED', 'FAILED', 'DEAD')",
            name="status_allowed",
        ),
        CheckConstraint("job_type IN ('FILE_SCAN_AND_PARSE')", name="job_type_allowed"),
        UniqueConstraint("tenant_id", "id", name="uq_worker_jobs_tenant_identity"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_worker_jobs_tenant_idempotency"),
        ForeignKeyConstraint(
            ["tenant_id", "media_object_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_worker_jobs_tenant_media",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            name="fk_worker_jobs_tenant_source_file",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "import_job_id"],
            ["import_jobs.tenant_id", "import_jobs.id"],
            name="fk_worker_jobs_tenant_import_job",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_worker_jobs_tenant_claim",
            "tenant_id",
            "status",
            "available_at",
            "lease_expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(
        String(60), nullable=False, default="FILE_SCAN_AND_PARSE"
    )
    media_object_id: Mapped[UUID] = mapped_column(nullable=False)
    source_file_id: Mapped[str] = mapped_column(String(40), nullable=False)
    import_job_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
