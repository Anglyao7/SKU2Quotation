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
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin, utcnow


class AIRunRow(AuditTimestampMixin, Base):
    """One deterministic provider attempt for a tenant-scoped AI task."""

    __tablename__ = "ai_runs"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint("length(input_hash) = 64", name="input_hash_sha256_length"),
        CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="output_hash_sha256_length",
        ),
        CheckConstraint(
            "(output_ref IS NULL AND output_hash IS NULL) OR "
            "(output_ref IS NOT NULL AND output_hash IS NOT NULL)",
            name="output_reference_complete",
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "provider_type IN ('FAKE', 'NATIVE')",
            name="provider_type_allowed",
        ),
        CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ai_runs_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "ai_task_id", "attempt_number", name="uq_ai_runs_task_attempt"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_ai_runs_tenant_task",
            ondelete="RESTRICT",
        ),
        Index("ix_ai_runs_tenant_task_status", "tenant_id", "ai_task_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ai_task_id: Mapped[UUID] = mapped_column(nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), default="FAKE", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="CREATED", nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class AITaskStepRow(AuditTimestampMixin, Base):
    """Recoverable execution checkpoint for the Product Intelligence workflow."""

    __tablename__ = "ai_task_steps"
    __table_args__ = (
        CheckConstraint("step_version >= 1", name="step_version_positive"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("length(input_hash) = 64", name="input_hash_sha256_length"),
        CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="output_hash_sha256_length",
        ),
        CheckConstraint(
            "(output_ref IS NULL AND output_hash IS NULL) OR "
            "(output_ref IS NOT NULL AND output_hash IS NOT NULL)",
            name="output_reference_complete",
        ),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_ai_task_steps_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "ai_task_id",
            "step_key",
            "step_version",
            name="uq_ai_task_steps_task_step_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_ai_task_steps_tenant_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "last_run_id"],
            ["ai_runs.tenant_id", "ai_runs.id"],
            name="fk_ai_task_steps_tenant_last_run",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_ai_task_steps_tenant_task_status", "tenant_id", "ai_task_id", "status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ai_task_id: Mapped[UUID] = mapped_column(nullable=False)
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    step_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ProductFieldCandidateRow(AuditTimestampMixin, Base):
    """Untrusted field suggestion that must be reviewed before any Product mutation."""

    __tablename__ = "product_field_candidates"
    __table_args__ = (
        CheckConstraint("candidate_index >= 0", name="candidate_index_nonnegative"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "confidence_policy_version >= 1", name="confidence_policy_version_positive"
        ),
        CheckConstraint("length(candidate_hash) = 64", name="candidate_hash_sha256_length"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "validation_status IN ('PASS', 'WARNING', 'FAILED')",
            name="validation_status_allowed",
        ),
        CheckConstraint(
            "review_status = 'AI_SUGGESTED'",
            name="review_status_candidate_only",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_product_field_candidates_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id",
            "ai_task_id",
            "candidate_group_key",
            "field_key",
            "candidate_hash",
            name="uq_product_field_candidates_task_field_hash",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_product_field_candidates_tenant_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_run_id"],
            ["ai_runs.tenant_id", "ai_runs.id"],
            name="fk_product_field_candidates_tenant_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_evidence_id"],
            ["ai_source_evidence.tenant_id", "ai_source_evidence.id"],
            name="fk_product_field_candidates_tenant_evidence",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_product_field_candidates_tenant_task_review",
            "tenant_id",
            "ai_task_id",
            "review_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ai_task_id: Mapped[UUID] = mapped_column(nullable=False)
    ai_run_id: Mapped[UUID] = mapped_column(nullable=False)
    source_evidence_id: Mapped[UUID] = mapped_column(nullable=False)
    candidate_group_key: Mapped[str] = mapped_column(String(160), nullable=False)
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    normalized_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    confidence_policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    extractor_key: Mapped[str] = mapped_column(String(120), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(30), default="PASS", nullable=False)
    review_status: Mapped[str] = mapped_column(
        String(30), default="AI_SUGGESTED", nullable=False
    )
    warnings: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    normalization_rule_version: Mapped[str] = mapped_column(
        String(80), default="raw-v1", nullable=False
    )
    normalization_trace: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ProductCandidateDecisionRow(AuditTimestampMixin, Base):
    """Append-only human decision that bridges candidates to a Product command."""

    __tablename__ = "product_candidate_decisions"
    __table_args__ = (
        CheckConstraint("action IN ('APPROVE', 'REJECT')", name="action_allowed"),
        CheckConstraint("status IN ('RECORDED', 'APPLIED')", name="status_allowed"),
        CheckConstraint("length(input_hash) = 64", name="input_hash_sha256_length"),
        CheckConstraint(
            "expected_product_version IS NULL OR expected_product_version >= 1",
            name="expected_product_version_positive",
        ),
        CheckConstraint(
            "applied_product_version IS NULL OR applied_product_version >= 1",
            name="applied_product_version_positive",
        ),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "(action = 'REJECT' AND status = 'RECORDED' "
            "AND product_id IS NULL AND applied_product_version IS NULL AND applied_at IS NULL) "
            "OR (action = 'APPROVE' AND status = 'APPLIED' "
            "AND product_id IS NOT NULL AND applied_product_version IS NOT NULL "
            "AND applied_at IS NOT NULL)",
            name="decision_lifecycle_consistent",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_product_candidate_decisions_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_product_candidate_decisions_tenant_idempotency",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_product_candidate_decisions_tenant_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_product_candidate_decisions_tenant_reviewer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_candidate_decisions_tenant_product",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_product_candidate_decisions_tenant_task_group",
            "tenant_id",
            "ai_task_id",
            "candidate_group_key",
            "created_at",
        ),
        Index(
            "uq_product_candidate_decisions_applied_group",
            "tenant_id",
            "ai_task_id",
            "candidate_group_key",
            unique=True,
            postgresql_where=text(
                "action = 'APPROVE' AND status = 'APPLIED' AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "action = 'APPROVE' AND status = 'APPLIED' AND deleted_at IS NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ai_task_id: Mapped[UUID] = mapped_column(nullable=False)
    candidate_group_key: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    human_values: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    normalization_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    normalization_rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reviewed_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    expected_product_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    product_id: Mapped[UUID | None] = mapped_column(nullable=True)
    applied_product_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class OutboxEventRow(AuditTimestampMixin, Base):
    """Tenant-scoped transactional outbox record for ProductCommitted projection work."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint("aggregate_version >= 1", name="aggregate_version_positive"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED', 'DEAD')",
            name="status_allowed",
        ),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND dead_lettered_at IS NULL) "
            "OR (status = 'DEAD' AND published_at IS NULL AND dead_lettered_at IS NOT NULL) "
            "OR (status IN ('PENDING', 'PROCESSING', 'FAILED') "
            "AND published_at IS NULL AND dead_lettered_at IS NULL)",
            name="publication_lifecycle_consistent",
        ),
        CheckConstraint(
            "(status = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="lease_lifecycle_consistent",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "event_type",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            name="uq_outbox_events_aggregate_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["product_candidate_decisions.tenant_id", "product_candidate_decisions.id"],
            name="fk_outbox_events_tenant_decision",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_outbox_events_unpublished",
            "available_at",
            "id",
            postgresql_where=text(
                "status IN ('PENDING', 'FAILED') AND dead_lettered_at IS NULL "
                "AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "status IN ('PENDING', 'FAILED') AND dead_lettered_at IS NULL "
                "AND deleted_at IS NULL"
            ),
        ),
        Index("ix_outbox_events_tenant_status", "tenant_id", "status", "occurred_at"),
        Index(
            "ix_outbox_events_tenant_claim",
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
    decision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class InboxEventRow(AuditTimestampMixin, Base):
    """Idempotency receipt for at-least-once domain-event consumers."""

    __tablename__ = "inbox_events"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'FAILED')", name="status_allowed"
        ),
        CheckConstraint(
            "(status = 'COMPLETED' AND processed_at IS NOT NULL) "
            "OR (status IN ('PROCESSING', 'FAILED') AND processed_at IS NULL)",
            name="processing_lifecycle_consistent",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_inbox_events_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "consumer_name", "event_id", name="uq_inbox_events_consumer_event"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["outbox_events.tenant_id", "outbox_events.id"],
            name="fk_inbox_events_tenant_outbox_event",
            ondelete="RESTRICT",
        ),
        Index("ix_inbox_events_tenant_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    consumer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    event_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
