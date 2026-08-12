from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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

from .database import Base
from .model_mixins import AuditTimestampMixin


class CatalogDeleteJobRow(AuditTimestampMixin, Base):
    """Observable tenant-scoped job for deleting an entire active catalog."""

    __tablename__ = "catalog_delete_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="progress_valid"),
        CheckConstraint("total_products >= 0", name="total_products_nonnegative"),
        CheckConstraint("total_skus >= 0", name="total_skus_nonnegative"),
        CheckConstraint(
            "deleted_product_count >= 0",
            name="deleted_product_count_nonnegative",
        ),
        CheckConstraint(
            "deleted_sku_count >= 0",
            name="deleted_sku_count_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_delete_jobs_tenant_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_catalog_delete_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_catalog_delete_jobs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "uq_catalog_delete_jobs_active_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text(
                "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
            ),
            sqlite_where=text(
                "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
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
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    stage: Mapped[str] = mapped_column(String(40), default="QUEUED", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_skus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_product_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    deleted_sku_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CatalogImportBatchRow(AuditTimestampMixin, Base):
    """One user-selected group of product workbooks imported together."""

    __tablename__ = "catalog_import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'PARTIALLY_REVOKED', 'REVOKED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "expected_file_count > 0 AND expected_file_count <= 100",
            name="expected_file_count_valid",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_import_batches_tenant_identity",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_catalog_import_batches_tenant_creator",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_catalog_import_batches_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expected_file_count: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default="ACTIVE", nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
