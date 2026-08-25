from datetime import datetime
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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class EmbeddingProviderSettingsRow(AuditTimestampMixin, Base):
    """Platform-wide OpenAI-compatible embedding provider configuration."""

    __tablename__ = "embedding_provider_settings"
    __table_args__ = (
        CheckConstraint(
            "provider = 'openai-compatible'",
            name="provider_supported",
        ),
        CheckConstraint(
            "dimensions >= 1 AND dimensions <= 2000",
            name="dimensions_supported",
        ),
        CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="timeout_supported",
        ),
        CheckConstraint(
            "max_retry_count >= 0 AND max_retry_count <= 10",
            name="max_retry_count_supported",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(40), default="openai-compatible", nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_retry_count: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ImageEmbeddingProviderSettingsRow(AuditTimestampMixin, Base):
    """Platform-wide DashScope multimodal embedding configuration."""

    __tablename__ = "image_embedding_provider_settings"
    __table_args__ = (
        CheckConstraint("provider = 'dashscope'", name="provider_supported"),
        CheckConstraint(
            "dimensions IN (256, 512, 768, 1024, 1536, 2048, 2560)",
            name="dimensions_supported",
        ),
        CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="timeout_supported",
        ),
        CheckConstraint(
            "max_retry_count >= 0 AND max_retry_count <= 5",
            name="max_retry_count_supported",
        ),
        CheckConstraint(
            "index_concurrency >= 1 AND index_concurrency <= 32",
            name="index_concurrency_supported",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(40), default="dashscope", nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_retry_count: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    index_concurrency: Mapped[int] = mapped_column(
        Integer,
        default=16,
        nullable=False,
    )
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RerankProviderSettingsRow(AuditTimestampMixin, Base):
    """Platform-wide Cohere-compatible rerank provider configuration."""

    __tablename__ = "rerank_provider_settings"
    __table_args__ = (
        CheckConstraint(
            "provider = 'cohere-compatible'",
            name="provider_supported",
        ),
        CheckConstraint(
            "timeout_ms >= 100 AND timeout_ms <= 800",
            name="timeout_ms_supported",
        ),
        CheckConstraint(
            "max_documents >= 5 AND max_documents <= 30",
            name="max_documents_supported",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(40), default="cohere-compatible", nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    max_documents: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class KnowledgeIndexJobRow(AuditTimestampMixin, Base):
    """Tenant-scoped, observable execution record for an embedding index update."""

    __tablename__ = "knowledge_index_jobs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('INCREMENTAL', 'FULL_REBUILD')",
            name="mode_allowed",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'PAUSED', 'SUCCEEDED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("total_products >= 0", name="total_products_nonnegative"),
        CheckConstraint(
            "processed_products >= 0 AND processed_products <= total_products",
            name="processed_products_valid",
        ),
        CheckConstraint("failed_products >= 0", name="failed_products_nonnegative"),
        CheckConstraint("embeddings >= 0", name="embeddings_nonnegative"),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_knowledge_index_jobs_tenant_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_knowledge_index_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_knowledge_index_jobs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "uq_knowledge_index_jobs_active_tenant",
            "tenant_id",
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
    requested_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    total_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embeddings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_product_id: Mapped[UUID | None] = mapped_column(nullable=True)
    current_product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_provider: Mapped[str] = mapped_column(String(60), nullable=False)
    model_name: Mapped[str] = mapped_column(String(300), nullable=False)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_product_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=list,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
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
