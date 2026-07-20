from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin, utcnow


JSON_DOCUMENT = JSON().with_variant(JSONB(none_as_null=True), "postgresql")
VECTOR_VALUE = VECTOR().with_variant(JSON(), "sqlite")


class KnowledgeDocumentRow(AuditTimestampMixin, Base):
    """Rebuildable, tenant-owned canonical projection of a Product version."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("source_entity_type = 'PRODUCT'", name="source_entity_type_allowed"),
        CheckConstraint("source_version >= 1", name="source_version_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint("field_policy_version >= 1", name="field_policy_version_positive"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="classification_allowed",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')",
            name="status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_documents_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "source_entity_type",
            "source_entity_id",
            "source_version",
            "schema_version",
            "field_policy_version",
            "locale",
            "content_hash",
            name="uq_knowledge_documents_projection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_entity_id"],
            ["products.tenant_id", "products.id"],
            name="fk_knowledge_documents_tenant_product",
            ondelete="CASCADE",
        ),
        Index(
            "ix_knowledge_documents_tenant_source_status",
            "tenant_id",
            "source_entity_type",
            "source_entity_id",
            "status",
        ),
        Index(
            "uq_knowledge_documents_active_source",
            "tenant_id",
            "source_entity_type",
            "source_entity_id",
            "locale",
            unique=True,
            postgresql_where=text("status = 'ACTIVE' AND deleted_at IS NULL"),
            sqlite_where=text("status = 'ACTIVE' AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    source_entity_type: Mapped[str] = mapped_column(String(40), default="PRODUCT", nullable=False)
    source_entity_id: Mapped[UUID] = mapped_column(nullable=False)
    source_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    document_type: Mapped[str] = mapped_column(String(60), default="PRODUCT_KNOWLEDGE", nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="und", nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field_policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(30), default="INTERNAL", nullable=False)
    permission_scope: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class KnowledgeChunkRow(AuditTimestampMixin, Base):
    """A deterministic, field-aware retrieval unit within one knowledge document."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "chunk_type IN ('OVERVIEW', 'SPECIFICATIONS', 'FEATURES', 'MARKETS', 'SUPPLY')",
            name="chunk_type_allowed",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')",
            name="status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_chunks_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_order",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["knowledge_documents.tenant_id", "knowledge_documents.id"],
            name="fk_knowledge_chunks_tenant_document",
            ondelete="CASCADE",
        ),
        Index(
            "ix_knowledge_chunks_tenant_document_status",
            "tenant_id",
            "document_id",
            "status",
        ),
        Index("ix_knowledge_chunks_content_hash", "tenant_id", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(40), nullable=False)
    section_path: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="und", nullable=False)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, default=dict, nullable=False
    )
    permission_scope: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class EmbeddingRow(AuditTimestampMixin, Base):
    """A model-versioned vector projection of one tenant-owned knowledge chunk."""

    __tablename__ = "embeddings"
    __table_args__ = (
        CheckConstraint("entity_type = 'KNOWLEDGE_CHUNK'", name="entity_type_allowed"),
        CheckConstraint("entity_version >= 1", name="entity_version_positive"),
        CheckConstraint("dimensions >= 1 AND dimensions <= 2000", name="dimensions_supported"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        CheckConstraint(
            "embedding_type IN ('TEXT', 'KNOWLEDGE_CHUNK')",
            name="embedding_type_allowed",
        ),
        CheckConstraint(
            "distance_metric IN ('COSINE', 'L2', 'INNER_PRODUCT')",
            name="distance_metric_allowed",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR activated_at IS NULL OR superseded_at >= activated_at",
            name="lifecycle_period_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_embeddings_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "entity_version",
            "embedding_type",
            "model_provider",
            "model_name",
            "model_version",
            "content_hash",
            name="uq_embeddings_projection",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "entity_id"],
            ["knowledge_chunks.tenant_id", "knowledge_chunks.id"],
            name="fk_embeddings_tenant_chunk",
            ondelete="CASCADE",
        ),
        Index(
            "ix_embeddings_tenant_model_status",
            "tenant_id",
            "model_name",
            "model_version",
            "dimensions",
            "status",
        ),
        Index(
            "uq_embeddings_active_entity_model",
            "tenant_id",
            "entity_type",
            "entity_id",
            "embedding_type",
            "model_provider",
            "model_name",
            "model_version",
            unique=True,
            postgresql_where=text("status = 'ACTIVE' AND deleted_at IS NULL"),
            sqlite_where=text("status = 'ACTIVE' AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(
        String(40), default="KNOWLEDGE_CHUNK", nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    entity_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    embedding_type: Mapped[str] = mapped_column(
        String(40), default="KNOWLEDGE_CHUNK", nullable=False
    )
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[str] = mapped_column(String(30), default="COSINE", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR_VALUE, nullable=False)
    permission_scope: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
