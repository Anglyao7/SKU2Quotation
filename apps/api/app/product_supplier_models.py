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
    JSON,
    Numeric,
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


class ProductCategoryRow(AuditTimestampMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')", name="status_allowed"),
        CheckConstraint("sort_order >= 0", name="sort_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_self_parent"),
        UniqueConstraint("tenant_id", "id", name="uq_product_categories_tenant_identity"),
        UniqueConstraint("tenant_id", "code", name="uq_product_categories_tenant_code"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_product_categories_tenant_parent",
            ondelete="RESTRICT",
        ),
        Index("ix_product_categories_tenant_parent_sort", "tenant_id", "parent_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(nullable=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ProductRow(AuditTimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'IN_REVIEW', 'ACTIVE', 'ARCHIVED')", name="status_allowed"
        ),
        CheckConstraint("current_version >= 1", name="current_version_positive"),
        CheckConstraint("search_document_version >= 0", name="search_version_nonnegative"),
        UniqueConstraint("tenant_id", "id", name="uq_products_tenant_identity"),
        UniqueConstraint("tenant_id", "product_code", name="uq_products_tenant_code"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_products_tenant_category",
            ondelete="RESTRICT",
        ),
        Index("ix_products_tenant_status_updated", "tenant_id", "status", "updated_at"),
        Index("ix_products_tenant_category", "tenant_id", "category_id"),
        Index(
            "ix_products_tenant_category_pinned",
            "tenant_id",
            "category_id",
            "storefront_pinned_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    default_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    search_document_version: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    storefront_pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProductVersionRow(AuditTimestampMixin, Base):
    """Immutable business snapshot created by a deterministic Product command."""

    __tablename__ = "product_versions"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256_length"),
        CheckConstraint("record_version >= 1", name="record_version_positive"),
        UniqueConstraint("tenant_id", "id", name="uq_product_versions_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "version_number",
            name="uq_product_versions_product_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "review_decision_id",
            name="uq_product_versions_review_decision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_versions_tenant_product",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "review_decision_id"],
            ["product_candidate_decisions.tenant_id", "product_candidate_decisions.id"],
            name="fk_product_versions_tenant_review_decision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_evidence_id"],
            ["ai_source_evidence.tenant_id", "ai_source_evidence.id"],
            name="fk_product_versions_tenant_source_evidence",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_product_versions_tenant_product_created",
            "tenant_id",
            "product_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_evidence_id: Mapped[UUID | None] = mapped_column(nullable=True)
    review_decision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    record_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ProductImageRow(AuditTimestampMixin, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        CheckConstraint("sort_order >= 0", name="sort_nonnegative"),
        CheckConstraint(
            "image_role IN ('MAIN', 'GALLERY', 'DETAIL', 'PACKAGING', 'CERTIFICATE')",
            name="image_role_allowed",
        ),
        CheckConstraint(
            "approval_status IN ('SOURCE', 'PENDING', 'APPROVED', 'REJECTED')",
            name="approval_status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_product_images_tenant_identity"),
        UniqueConstraint("tenant_id", "object_key", name="uq_product_images_tenant_object_key"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_images_tenant_product",
            ondelete="CASCADE",
        ),
        Index("ix_product_images_tenant_product_sort", "tenant_id", "product_id", "sort_order"),
        Index("ix_product_images_tenant_sha256", "tenant_id", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(30), default="S3", nullable=False)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_role: Mapped[str] = mapped_column(String(30), default="GALLERY", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(30), default="SOURCE", nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ProductAttributeRow(AuditTimestampMixin, Base):
    __tablename__ = "product_attributes"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_number IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN value_json IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="exactly_one_typed_value",
        ),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        CheckConstraint(
            "review_status IN ('AI_SUGGESTED', 'CONFIRMED', 'REJECTED')",
            name="review_status_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_product_attributes_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_attributes_tenant_product",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "attribute_definition_id"],
            ["attribute_definitions.tenant_id", "attribute_definitions.id"],
            name="fk_product_attributes_tenant_definition",
            ondelete="RESTRICT",
        ),
        Index("ix_product_attributes_tenant_product_key", "tenant_id", "product_id", "attribute_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    attribute_definition_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attribute_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="AI_SUGGESTED", nullable=False)


class SupplierProductRow(AuditTimestampMixin, Base):
    __tablename__ = "supplier_products"
    __table_args__ = (
        CheckConstraint("moq IS NULL OR moq >= 0", name="moq_nonnegative"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_nonnegative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'UNVERIFIED')", name="status_allowed"),
        UniqueConstraint("tenant_id", "id", name="uq_supplier_products_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "supplier_id",
            "product_id",
            "supplier_sku",
            name="uq_supplier_products_tenant_source_sku",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_supplier_products_tenant_supplier",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_supplier_products_tenant_sku",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_supplier_products_tenant_product",
            ondelete="CASCADE",
        ),
        Index("ix_supplier_products_tenant_supplier", "tenant_id", "supplier_id"),
        Index("ix_supplier_products_tenant_product", "tenant_id", "product_id"),
        Index("ix_supplier_products_tenant_sku", "tenant_id", "sku_id"),
        Index(
            "uq_supplier_products_tenant_null_sku",
            "tenant_id",
            "supplier_id",
            "product_id",
            unique=True,
            postgresql_where=text("supplier_sku IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("supplier_sku IS NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(40), nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID | None] = mapped_column(nullable=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(160), nullable=True)
    supplier_product_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    moq: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    moq_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED", nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class SupplierScoreRow(AuditTimestampMixin, Base):
    """Append-style supplier score snapshots; physical name follows the Phase 2 contract."""

    __tablename__ = "supplier_score"
    __table_args__ = (
        CheckConstraint("quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)", name="quality_range"),
        CheckConstraint("price_score IS NULL OR (price_score >= 0 AND price_score <= 100)", name="price_range"),
        CheckConstraint("delivery_score IS NULL OR (delivery_score >= 0 AND delivery_score <= 100)", name="delivery_range"),
        CheckConstraint("response_score IS NULL OR (response_score >= 0 AND response_score <= 100)", name="response_range"),
        CheckConstraint("risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)", name="risk_range"),
        CheckConstraint("overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)", name="overall_range"),
        CheckConstraint("sample_size >= 0", name="sample_size_nonnegative"),
        UniqueConstraint("tenant_id", "id", name="uq_supplier_score_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_supplier_score_tenant_supplier",
            ondelete="CASCADE",
        ),
        Index("ix_supplier_score_tenant_supplier_calculated", "tenant_id", "supplier_id", "calculated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(40), nullable=False)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    price_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    delivery_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    response_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    method_version: Mapped[str] = mapped_column(String(50), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    evidence_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
