from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .model_mixins import AuditTimestampMixin


class StorefrontCustomPageRow(AuditTimestampMixin, Base):
    """Tenant-owned HTML page exposed through the public storefront navigation."""

    __tablename__ = "storefront_custom_pages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "slug",
            name="uq_storefront_custom_pages_tenant_slug",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_custom_pages_tenant_identity",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "ix_storefront_custom_pages_tenant_navigation",
            "tenant_id",
            "enabled",
            "sort_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
