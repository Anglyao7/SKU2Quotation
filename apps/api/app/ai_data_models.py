from datetime import datetime
from decimal import Decimal
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin


# PostgreSQL owns the production contract; SQLite remains the lightweight local/test adapter.
JSON_DOCUMENT = JSON().with_variant(JSONB(none_as_null=True), "postgresql")


class AIProviderRouteRow(AuditTimestampMixin, Base):
    """Versioned, tenant-owned provider routing metadata; never stores credentials."""

    __tablename__ = "ai_provider_routes"
    __table_args__ = (
        CheckConstraint("route_version >= 1", name="route_version_positive"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'RETIRED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "max_data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="classification_allowed",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
            name="effective_period_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ai_provider_routes_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "route_key",
            "route_version",
            name="uq_ai_provider_routes_tenant_key_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approved_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_ai_provider_routes_tenant_approver",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_ai_provider_routes_tenant_capability_status",
            "tenant_id",
            "capability",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    route_key: Mapped[str] = mapped_column(String(100), nullable=False)
    route_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    primary_adapter: Mapped[str] = mapped_column(String(160), nullable=False)
    fallback_adapters: Mapped[list[dict[str, Any]] | list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    data_region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_data_classification: Mapped[str] = mapped_column(
        String(30), default="INTERNAL", nullable=False
    )
    routing_policy: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    retention_policy: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    credential_secret_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class AITaskRow(AuditTimestampMixin, Base):
    """One tenant-scoped AI business intent; provider attempts are intentionally deferred."""

    __tablename__ = "ai_tasks"
    __table_args__ = (
        CheckConstraint("task_version >= 1", name="task_version_positive"),
        CheckConstraint("input_schema_version >= 1", name="input_schema_version_positive"),
        CheckConstraint("business_entity_version IS NULL OR business_entity_version >= 1", name="entity_version_positive"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint("priority >= 0 AND priority <= 1000", name="priority_range"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        CheckConstraint("length(input_hash) = 64", name="input_hash_sha256_length"),
        CheckConstraint(
            "(business_entity_type IS NULL AND business_entity_id IS NULL) OR "
            "(business_entity_type IS NOT NULL AND business_entity_id IS NOT NULL)",
            name="entity_reference_complete",
        ),
        CheckConstraint(
            "risk_level IN ('L1_ASSISTIVE', 'L2_DRAFTING', 'L3_DECISION_SUPPORT', 'L4_HIGH_IMPACT')",
            name="risk_level_allowed",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'QUEUED', 'RUNNING', 'VALIDATING', 'SUCCEEDED', "
            "'NEEDS_REVIEW', 'PARTIAL', 'FAILED', 'CANCELLED', 'EXPIRED')",
            name="status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ai_tasks_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_ai_tasks_tenant_idempotency"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_ai_tasks_tenant_requester",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "provider_route_id"],
            ["ai_provider_routes.tenant_id", "ai_provider_routes.id"],
            name="fk_ai_tasks_tenant_provider_route",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_ai_tasks_tenant_status_priority_created",
            "tenant_id",
            "status",
            "priority",
            "created_at",
        ),
        Index(
            "ix_ai_tasks_tenant_business_entity",
            "tenant_id",
            "business_entity_type",
            "business_entity_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    task_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    business_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    business_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_entity_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    risk_level: Mapped[str] = mapped_column(
        String(30), default="L1_ASSISTIVE", nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    budget_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    requested_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    provider_route_id: Mapped[UUID | None] = mapped_column(nullable=True)
    route_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class AISourceEvidenceRow(AuditTimestampMixin, Base):
    """Minimal source lineage using controlled references and hashes, not raw source content."""

    __tablename__ = "ai_source_evidence"
    __table_args__ = (
        CheckConstraint("source_version IS NULL OR source_version >= 1", name="source_version_positive"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        CheckConstraint("raw_value_hash IS NULL OR length(raw_value_hash) = 64", name="raw_value_hash_sha256_length"),
        CheckConstraint("length(evidence_hash) = 64", name="evidence_hash_sha256_length"),
        CheckConstraint("raw_value_ref IS NULL OR raw_value_hash IS NOT NULL", name="raw_reference_has_hash"),
        CheckConstraint(
            "classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="classification_allowed",
        ),
        CheckConstraint(
            "location_type IN ('SHEET_CELL_RANGE', 'PAGE_BOX', 'SLIDE_SHAPE', "
            "'IMAGE_CROP', 'ENTITY_FIELD', 'FILE_OBJECT')",
            name="location_type_allowed",
        ),
        CheckConstraint(
            "(parser_identifier IS NULL AND parser_version IS NULL) OR "
            "(parser_identifier IS NOT NULL AND parser_version IS NOT NULL)",
            name="parser_reference_complete",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ai_source_evidence_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "source_entity_type",
            "source_entity_id",
            "location_type",
            "evidence_hash",
            name="uq_ai_source_evidence_tenant_source_hash",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_ai_source_evidence_tenant_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            name="fk_ai_source_evidence_tenant_source_file",
            ondelete="RESTRICT",
        ),
        Index("ix_ai_source_evidence_tenant_task", "tenant_id", "ai_task_id"),
        Index(
            "ix_ai_source_evidence_tenant_source",
            "tenant_id",
            "source_entity_type",
            "source_entity_id",
        ),
        Index("ix_ai_source_evidence_tenant_file", "tenant_id", "source_file_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ai_task_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_file_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    location_type: Mapped[str] = mapped_column(String(40), nullable=False)
    location: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    raw_value_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_value_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    classification: Mapped[str] = mapped_column(
        String(30), default="INTERNAL", nullable=False
    )
    permission_scope: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    parser_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
