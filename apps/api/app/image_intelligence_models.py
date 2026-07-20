from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .knowledge_embedding_models import VECTOR_VALUE
from .model_mixins import AuditTimestampMixin, utcnow


class VisionObservationRow(AuditTimestampMixin, Base):
    __tablename__ = "vision_observations"
    __table_args__ = (
        CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality_score_range"),
        CheckConstraint("status IN ('OBSERVED', 'FAILED', 'STALE', 'ARCHIVED')", name="status_allowed"),
        UniqueConstraint("tenant_id", "id", name="uq_vision_observations_tenant_identity"),
        UniqueConstraint("tenant_id", "product_image_id", "model_provider", "model_name", "model_version", "content_hash", name="uq_vision_observations_projection"),
        ForeignKeyConstraint(["tenant_id", "product_image_id"], ["product_images.tenant_id", "product_images.id"], name="fk_vision_observations_tenant_image", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_vision_observations_tenant_product", ondelete="CASCADE"),
        Index("ix_vision_observations_tenant_image_status", "tenant_id", "product_image_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_image_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    labels: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    risks: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OBSERVED", nullable=False)


class ImageEmbeddingRow(AuditTimestampMixin, Base):
    __tablename__ = "image_embeddings"
    __table_args__ = (
        CheckConstraint("product_version >= 1", name="product_version_positive"),
        CheckConstraint("dimensions = 384", name="dimensions_supported"),
        CheckConstraint("distance_metric = 'COSINE'", name="distance_metric_allowed"),
        CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="quality_score_range"),
        CheckConstraint("status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')", name="status_allowed"),
        UniqueConstraint("tenant_id", "id", name="uq_image_embeddings_tenant_identity"),
        UniqueConstraint("tenant_id", "product_image_id", "model_provider", "model_name", "model_version", "content_hash", name="uq_image_embeddings_projection"),
        ForeignKeyConstraint(["tenant_id", "product_image_id"], ["product_images.tenant_id", "product_images.id"], name="fk_image_embeddings_tenant_image", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_image_embeddings_tenant_product", ondelete="CASCADE"),
        Index("ix_image_embeddings_tenant_model_status", "tenant_id", "model_name", "model_version", "status"),
        Index("uq_image_embeddings_active_image_model", "tenant_id", "product_image_id", "model_provider", "model_name", "model_version", unique=True, postgresql_where=text("status = 'ACTIVE' AND deleted_at IS NULL"), sqlite_where=text("status = 'ACTIVE' AND deleted_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_image_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    product_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(default=384, nullable=False)
    distance_metric: Mapped[str] = mapped_column(String(20), default="COSINE", nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR_VALUE, nullable=False)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    permission_scope: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImageSearchRow(AuditTimestampMixin, Base):
    __tablename__ = "image_searches"
    __table_args__ = (
        CheckConstraint("dimensions = 384", name="dimensions_supported"),
        CheckConstraint("status IN ('COMPLETED', 'NO_RELIABLE_MATCH', 'FAILED', 'EXPIRED')", name="status_allowed"),
        UniqueConstraint("tenant_id", "id", name="uq_image_searches_tenant_identity"),
        ForeignKeyConstraint(["tenant_id", "requested_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_image_searches_tenant_requester", ondelete="RESTRICT"),
        Index("ix_image_searches_tenant_expiry", "tenant_id", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    requested_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    query_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(default=384, nullable=False)
    query_embedding: Mapped[list[float] | None] = mapped_column(VECTOR_VALUE, nullable=True)
    result_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
