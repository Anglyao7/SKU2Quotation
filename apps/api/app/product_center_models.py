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


SKU_TEMPLATE_SOURCE_OPTION_KEY = "_sku2quotation"


class SkuRow(AuditTimestampMixin, Base):
    __tablename__ = "skus"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'ARCHIVED')", name="status_allowed"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("default_moq IS NULL OR default_moq >= 0", name="moq_nonnegative"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="weight_nonnegative"),
        UniqueConstraint("tenant_id", "id", name="uq_skus_tenant_identity"),
        UniqueConstraint("tenant_id", "sku_code", name="uq_skus_tenant_code"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_skus_tenant_product",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"],
            ["suppliers.tenant_id", "suppliers.id"],
            name="fk_skus_tenant_supplier",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "latest_import_job_id"],
            ["import_jobs.tenant_id", "import_jobs.id"],
            name="fk_skus_tenant_latest_import_job",
            ondelete="RESTRICT",
        ),
        Index("ix_skus_tenant_product_status", "tenant_id", "product_id", "status"),
        Index("ix_skus_tenant_supplier", "tenant_id", "supplier_id"),
        Index(
            "ix_skus_tenant_latest_import_job",
            "tenant_id",
            "latest_import_job_id",
        ),
        Index("ix_skus_tenant_status_updated", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latest_import_job_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    sku_code: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    option_values: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    barcode: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_moq: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    moq_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    weight_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AttributeDefinitionRow(AuditTimestampMixin, Base):
    __tablename__ = "attribute_definitions"
    __table_args__ = (
        CheckConstraint(
            "data_type IN ('TEXT', 'NUMBER', 'BOOLEAN', 'ENUM')", name="data_type_allowed"
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status_allowed"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(data_type = 'ENUM' AND enum_values IS NOT NULL) OR data_type <> 'ENUM'",
            name="enum_values_required",
        ),
        UniqueConstraint(
            "tenant_id", "category_id", "attribute_key", name="uq_attribute_definitions_category_key"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_attribute_definitions_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_attribute_definitions_tenant_category",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_attribute_definitions_global_key",
            "tenant_id",
            "attribute_key",
            unique=True,
            postgresql_where=text("category_id IS NULL AND deleted_at IS NULL"),
            sqlite_where=text("category_id IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "ix_attribute_definitions_tenant_category_status",
            "tenant_id",
            "category_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[UUID | None] = mapped_column(nullable=True)
    attribute_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enum_values: Mapped[list[str] | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_variant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_filterable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_matchable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class SupplierPriceRow(AuditTimestampMixin, Base):
    __tablename__ = "supplier_prices"
    __table_args__ = (
        CheckConstraint("min_quantity >= 0", name="min_quantity_nonnegative"),
        CheckConstraint(
            "max_quantity IS NULL OR max_quantity >= min_quantity",
            name="quantity_range_valid",
        ),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)", name="currency_format"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="validity_range_valid"
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'SUPERSEDED', 'REVOKED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "(status = 'CONFIRMED' AND confirmed_by_membership_id IS NOT NULL "
            "AND confirmed_at IS NOT NULL) OR status <> 'CONFIRMED'",
            name="confirmation_required",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_supplier_prices_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "supplier_product_id"],
            ["supplier_products.tenant_id", "supplier_products.id"],
            name="fk_supplier_prices_tenant_supplier_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_supplier_prices_tenant_sku",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_evidence_id"],
            ["ai_source_evidence.tenant_id", "ai_source_evidence.id"],
            name="fk_supplier_prices_tenant_evidence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "confirmed_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supplier_prices_tenant_confirmer",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "supersedes_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            name="fk_supplier_prices_tenant_superseded_price",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_supplier_prices_tenant_source_validity",
            "tenant_id",
            "supplier_product_id",
            "status",
            "valid_from",
        ),
        Index("ix_supplier_prices_tenant_sku", "tenant_id", "sku_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    supplier_product_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID | None] = mapped_column(nullable=True)
    min_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    max_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    incoterm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="CONFIRMED", nullable=False)
    source_evidence_id: Mapped[UUID | None] = mapped_column(nullable=True)
    confirmed_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_price_id: Mapped[UUID | None] = mapped_column(nullable=True)


class ProductAuditEventRow(AuditTimestampMixin, Base):
    __tablename__ = "product_audit_events"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('PRODUCT', 'SKU', 'PRICE', 'CATEGORY', "
            "'ATTRIBUTE_DEFINITION', 'CANDIDATE_REVIEW')",
            name="entity_type_allowed",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_product_audit_events_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_audit_events_tenant_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_product_audit_events_tenant_actor",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_product_audit_events_tenant_product_time",
            "tenant_id",
            "product_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID | None] = mapped_column(nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    actor_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
