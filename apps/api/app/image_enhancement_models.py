from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin, utcnow


class ImageEnhancementTaskRow(AuditTimestampMixin, Base):
    """Durable product-image enhancement run owned by one merchant."""

    __tablename__ = "image_enhancement_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint("output_format = 'url'", name="output_format_allowed"),
        CheckConstraint("total_items >= 0", name="total_items_nonnegative"),
        CheckConstraint("completed_items >= 0", name="completed_items_nonnegative"),
        CheckConstraint("failed_items >= 0", name="failed_items_nonnegative"),
        CheckConstraint("cancelled_items >= 0", name="cancelled_items_nonnegative"),
        UniqueConstraint("tenant_id", "id", name="uq_image_enhancement_tasks_tenant_identity"),
        Index("ix_image_enhancement_tasks_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_image_enhancement_tasks_active", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    prompt: Mapped[str] = mapped_column(
        Text,
        default=(
            "Enhance only the provided product image: make it sharper, clearer, and less noisy. "
            "The input image is the source of truth. Preserve the exact product, colors, materials, "
            "shape, proportions, existing text, markings, existing logos, background, lighting, and composition. "
            "Do not add, remove, redraw, or invent any logo, text, label, accessory, decoration, prop, or other object. "
            "Do not change the background or create a new design."
        ),
        nullable=False,
    )
    size: Mapped[str] = mapped_column(String(32), default="1024x1024", nullable=False)
    output_format: Mapped[str] = mapped_column(String(20), default="url", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancelled_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImageEnhancementItemRow(AuditTimestampMixin, Base):
    """One unique source image within an enhancement task."""

    __tablename__ = "image_enhancement_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'APPLIED')",
            name="review_status_allowed",
        ),
        UniqueConstraint("task_id", "source_image_id", name="uq_image_enhancement_items_source"),
        Index("ix_image_enhancement_items_task_status", "task_id", "status"),
        Index("ix_image_enhancement_items_tenant_product", "tenant_id", "product_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("image_enhancement_tasks.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    source_image_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("product_images.id", ondelete="SET NULL"), nullable=True
    )
    sku_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    sku_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    product_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_image_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    result_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    result_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
