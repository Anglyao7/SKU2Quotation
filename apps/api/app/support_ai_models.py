from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from .model_mixins import AuditTimestampMixin


class SupportAIProviderSettingsRow(AuditTimestampMixin, Base):
    """Reusable platform-owned OpenAI-compatible generation profile."""

    __tablename__ = "support_ai_provider_settings"
    __table_args__ = (
        CheckConstraint(
            "provider = 'openai-compatible'",
            name="provider_supported",
        ),
        CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 180",
            name="timeout_supported",
        ),
        CheckConstraint(
            "max_output_tokens >= 128 AND max_output_tokens <= 32768",
            name="max_output_tokens_supported",
        ),
        CheckConstraint(
            "temperature >= 0 AND temperature <= 2",
            name="temperature_supported",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint(
            "configuration_name", name="uq_support_ai_provider_configuration_name"
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    configuration_name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(40), default="openai-compatible", nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=45, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), default=Decimal("0.100"), nullable=False
    )
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SupportAIAgentRow(AuditTimestampMixin, Base):
    """Platform-owned intelligent agent reusable across one or more stores."""

    __tablename__ = "support_ai_agents"
    __table_args__ = (
        CheckConstraint("length(agent_code) = 8", name="agent_code_length"),
        CheckConstraint(
            "min_retrieval_score >= 0 AND min_retrieval_score <= 1",
            name="retrieval_score_range",
        ),
        CheckConstraint(
            "min_answer_confidence >= 0 AND min_answer_confidence <= 1",
            name="answer_confidence_range",
        ),
        CheckConstraint(
            "max_sources >= 1 AND max_sources <= 12",
            name="max_sources_range",
        ),
        CheckConstraint(
            "daily_auto_reply_limit >= 1 AND daily_auto_reply_limit <= 100000",
            name="daily_limit_range",
        ),
        UniqueConstraint("agent_code", name="uq_support_ai_agents_agent_code"),
        Index("ix_support_ai_agents_enabled_updated", "enabled", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_company_introduction: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    public_service_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_setting_id: Mapped[str | None] = mapped_column(
        ForeignKey("support_ai_provider_settings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sku_knowledge_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    file_knowledge_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    multilingual_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    min_retrieval_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), default=Decimal("0.12000"), nullable=False
    )
    min_answer_confidence: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), default=Decimal("0.65000"), nullable=False
    )
    max_sources: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    daily_auto_reply_limit: Mapped[int] = mapped_column(
        Integer, default=500, nullable=False
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    handoff_messages: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SupportAISettingsRow(AuditTimestampMixin, Base):
    """Store-owned customer-service AI configuration."""

    __tablename__ = "support_ai_settings"
    __table_args__ = (
        CheckConstraint(
            "min_retrieval_score >= 0 AND min_retrieval_score <= 1",
            name="retrieval_score_range",
        ),
        CheckConstraint(
            "min_answer_confidence >= 0 AND min_answer_confidence <= 1",
            name="answer_confidence_range",
        ),
        CheckConstraint(
            "max_sources >= 1 AND max_sources <= 12",
            name="max_sources_range",
        ),
        CheckConstraint(
            "daily_auto_reply_limit >= 1 AND daily_auto_reply_limit <= 100000",
            name="daily_limit_range",
        ),
        CheckConstraint("prompt_version >= 1", name="prompt_version_positive"),
        UniqueConstraint("tenant_id", name="uq_support_ai_settings_tenant"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_ai_agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_setting_id: Mapped[str | None] = mapped_column(
        ForeignKey("support_ai_provider_settings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    public_company_introduction: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    public_service_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku_knowledge_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    file_knowledge_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    multilingual_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    min_retrieval_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), default=Decimal("0.12000"), nullable=False
    )
    min_answer_confidence: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), default=Decimal("0.65000"), nullable=False
    )
    max_sources: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    daily_auto_reply_limit: Mapped[int] = mapped_column(
        Integer, default=500, nullable=False
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    handoff_messages: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    prompt_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SupportAIKnowledgeBaseRow(AuditTimestampMixin, Base):
    """A tenant-scoped knowledge base owned by exactly one AI agent.

    An agent may own many knowledge bases.  Files are attached to a knowledge
    base rather than directly to an agent so that uploads, approvals, training
    and future knowledge-base settings have an explicit lifecycle boundary.
    """

    __tablename__ = "support_ai_knowledge_bases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="status_allowed",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_support_ai_knowledge_bases_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id", "agent_id", "name",
            name="uq_support_ai_knowledge_bases_tenant_agent_name",
        ),
        Index(
            "ix_support_ai_knowledge_bases_tenant_agent_status",
            "tenant_id",
            "agent_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_ai_agents.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SupportAIKnowledgeSourceRow(AuditTimestampMixin, Base):
    """An uploaded and explicitly approved customer-facing knowledge source."""

    __tablename__ = "support_ai_knowledge_sources"
    __table_args__ = (
        CheckConstraint("source_type = 'FILE'", name="source_type_allowed"),
        CheckConstraint(
            "classification IN ('PUBLIC', 'CUSTOMER_APPROVED')",
            name="classification_allowed",
        ),
        CheckConstraint(
            "status IN ('PROCESSING', 'READY', 'APPROVED', 'REVOKED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_support_ai_knowledge_sources_tenant_identity"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "media_object_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_support_ai_knowledge_sources_tenant_media",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["support_ai_knowledge_bases.tenant_id", "support_ai_knowledge_bases.id"],
            name="fk_support_ai_knowledge_sources_tenant_knowledge_base",
            ondelete="CASCADE",
        ),
        Index(
            "ix_support_ai_knowledge_sources_tenant_status",
            "tenant_id",
            "status",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_ai_agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledge_base_id: Mapped[UUID | None] = mapped_column(
        nullable=True,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(20), default="FILE", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[str] = mapped_column(
        String(30), default="CUSTOMER_APPROVED", nullable=False
    )
    language: Mapped[str] = mapped_column(String(35), default="und", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PROCESSING", nullable=False)
    media_object_id: Mapped[UUID] = mapped_column(nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class SupportAIKnowledgeChunkRow(AuditTimestampMixin, Base):
    __tablename__ = "support_ai_knowledge_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_length"),
        CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'DELETED')",
            name="status_allowed",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_support_ai_knowledge_chunks_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id",
            "source_id",
            "chunk_index",
            name="uq_support_ai_knowledge_chunks_source_order",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["support_ai_knowledge_sources.tenant_id", "support_ai_knowledge_sources.id"],
            name="fk_support_ai_knowledge_chunks_tenant_source",
            ondelete="CASCADE",
        ),
        Index(
            "ix_support_ai_knowledge_chunks_tenant_source_status",
            "tenant_id",
            "source_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    language: Mapped[str] = mapped_column(String(35), default="und", nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        JSON_DOCUMENT, nullable=True
    )
    embedding_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(300), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)


class SupportAIIngestionJobRow(AuditTimestampMixin, Base):
    __tablename__ = "support_ai_ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_range"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_support_ai_ingestion_jobs_tenant_identity"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["support_ai_knowledge_sources.tenant_id", "support_ai_knowledge_sources.id"],
            name="fk_support_ai_ingestion_jobs_tenant_source",
            ondelete="CASCADE",
        ),
        Index(
            "ix_support_ai_ingestion_jobs_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parser_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunks_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SupportAIRunRow(AuditTimestampMixin, Base):
    """One traceable attempt to answer a visitor or a test-lab question."""

    __tablename__ = "support_ai_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('CHAT', 'TEST')",
            name="trigger_type_allowed",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'NEEDS_REVIEW', "
            "'HANDOFF', 'FAILED', 'CANCELLED', 'SKIPPED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint("prompt_version >= 1", name="prompt_version_positive"),
        UniqueConstraint("tenant_id", "id", name="uq_support_ai_runs_tenant_identity"),
        UniqueConstraint("tenant_id", "ai_task_id", name="uq_support_ai_runs_tenant_task"),
        ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_support_ai_runs_tenant_task",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["storefront_chat_conversations.tenant_id", "storefront_chat_conversations.id"],
            name="fk_support_ai_runs_tenant_conversation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "input_message_id"],
            ["storefront_chat_messages.tenant_id", "storefront_chat_messages.id"],
            name="fk_support_ai_runs_tenant_input_message",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "output_message_id"],
            ["storefront_chat_messages.tenant_id", "storefront_chat_messages.id"],
            name="fk_support_ai_runs_tenant_output_message",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_support_ai_runs_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "uq_support_ai_runs_input_message",
            "tenant_id",
            "input_message_id",
            unique=True,
            postgresql_where=text("input_message_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("input_message_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    ai_task_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    input_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    output_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_setting_id: Mapped[str | None] = mapped_column(
        ForeignKey("support_ai_provider_settings.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    visitor_locale: Mapped[str] = mapped_column(String(35), default="und", nullable=False)
    detected_language: Mapped[str | None] = mapped_column(String(35), nullable=True)
    normalized_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5), nullable=True)
    handoff_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    model_display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retrieval_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision_trace: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SupportAIEvidenceUseRow(AuditTimestampMixin, Base):
    """Immutable source excerpt used by a support answer and rendered as a citation."""

    __tablename__ = "support_ai_evidence_uses"
    __table_args__ = (
        CheckConstraint("citation_number >= 1", name="citation_number_positive"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint(
            "source_type IN ('SKU', 'FILE')",
            name="source_type_allowed",
        ),
        CheckConstraint(
            "classification IN ('PUBLIC', 'CUSTOMER_APPROVED')",
            name="classification_allowed",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_support_ai_evidence_uses_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "citation_number",
            name="uq_support_ai_evidence_uses_run_citation",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["support_ai_runs.tenant_id", "support_ai_runs.id"],
            name="fk_support_ai_evidence_uses_tenant_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_source_id"],
            ["support_ai_knowledge_sources.tenant_id", "support_ai_knowledge_sources.id"],
            name="fk_support_ai_evidence_uses_tenant_source",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_support_ai_evidence_uses_tenant_run",
            "tenant_id",
            "run_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(nullable=False)
    citation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    knowledge_source_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
