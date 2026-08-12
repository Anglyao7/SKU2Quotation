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
)
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class TenantPublicProfileRow(AuditTimestampMixin, Base):
    """Public-safe tenant projection used to resolve a store before RLS is bound."""

    __tablename__ = "tenant_public_profiles"
    __table_args__ = (
        CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'SUSPENDED')",
            name="publication_status_allowed",
        ),
        CheckConstraint(
            "all_products_position >= 0",
            name="all_products_position_nonnegative",
        ),
        UniqueConstraint("slug", name="uq_tenant_public_profiles_slug"),
        Index(
            "ix_tenant_public_profiles_publication_slug",
            "publication_status",
            "slug",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    legacy_slugs: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    logo_object_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    publication_status: Mapped[str] = mapped_column(
        String(20), default="DRAFT", nullable=False
    )
    all_products_position: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    storefront_locales: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=lambda: ["zh-CN", "en-US"],
        nullable=False,
    )
    hot_products_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    category_showcase_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    support_widget_config: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        default=dict,
        nullable=False,
    )


class PublicCatalogOfferRow(AuditTimestampMixin, Base):
    """Explicit public selling offer; supplier procurement costs never enter this table."""

    __tablename__ = "public_catalog_offers"
    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'SUSPENDED')",
            name="publication_status_allowed",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="validity_range_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_public_catalog_offers_tenant_identity"),
        UniqueConstraint("tenant_id", "sku_id", name="uq_public_catalog_offers_tenant_sku"),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_public_catalog_offers_tenant_sku",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_public_catalog_offers_tenant_publication",
            "tenant_id",
            "publication_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    display_tag: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tag_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    publication_status: Mapped[str] = mapped_column(
        String(20), default="DRAFT", nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CatalogShareRow(AuditTimestampMixin, Base):
    """Tenant-scoped, opaque storefront share links for products or a category."""

    __tablename__ = "catalog_shares"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('PRODUCTS', 'CATEGORY')",
            name="target_type_allowed",
        ),
        CheckConstraint(
            "logo_position IN ('NONE', 'TOP_LEFT', 'TOP_RIGHT')",
            name="logo_position_allowed",
        ),
        CheckConstraint("item_count > 0", name="item_count_positive"),
        CheckConstraint("length(fingerprint) = 64", name="fingerprint_sha256_length"),
        CheckConstraint(
            "(target_type = 'PRODUCTS' AND category_id IS NULL) OR "
            "(target_type = 'CATEGORY' AND category_id IS NOT NULL)",
            name="target_shape_valid",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_catalog_shares_tenant_identity"),
        UniqueConstraint("share_token", name="uq_catalog_shares_token"),
        UniqueConstraint(
            "tenant_id", "fingerprint", name="uq_catalog_shares_tenant_fingerprint"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_catalog_shares_tenant_category",
            ondelete="RESTRICT",
        ),
        Index("ix_catalog_shares_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    share_token: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    category_id: Mapped[UUID | None] = mapped_column(nullable=True)
    category_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    logo_position: Mapped[str] = mapped_column(
        String(20), default="NONE", nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PublicQuoteDraftRow(AuditTimestampMixin, Base):
    """Customer-submitted price indication awaiting the authoritative quotation flow."""

    __tablename__ = "public_quote_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'COMPLETED', 'CANCELLED', 'EXPIRED')",
            name="status_allowed",
        ),
        CheckConstraint("subtotal_amount >= 0", name="subtotal_nonnegative"),
        CheckConstraint("estimated_total >= 0", name="estimated_total_nonnegative"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_sha256_length"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_public_quote_drafts_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "request_number", name="uq_public_quote_drafts_tenant_number"
        ),
        Index(
            "ix_public_quote_drafts_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_public_quote_drafts_tenant_submitter",
            ondelete="SET NULL",
        ),
        Index(
            "ix_public_quote_drafts_tenant_submitter_created",
            "tenant_id",
            "submitted_by_membership_id",
            "created_at",
        ),
        Index(
            "ix_public_quote_drafts_tenant_visitor_updated",
            "tenant_id",
            "visitor_token_hash",
            "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    request_number: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="PENDING_CONFIRMATION", nullable=False
    )
    submitted_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    visitor_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_locale: Mapped[str] = mapped_column(
        String(20), default="zh-CN", nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    estimated_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    disclaimer_version: Mapped[str] = mapped_column(String(40), nullable=False)


class PublicQuoteDraftItemRow(AuditTimestampMixin, Base):
    __tablename__ = "public_quote_draft_items"
    __table_args__ = (
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("minimum_order_quantity > 0", name="moq_positive"),
        CheckConstraint("unit_price_snapshot >= 0", name="unit_price_nonnegative"),
        CheckConstraint("line_total >= 0", name="line_total_nonnegative"),
        CheckConstraint("product_version >= 1", name="product_version_positive"),
        CheckConstraint("sku_version >= 1", name="sku_version_positive"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_public_quote_draft_items_tenant_identity"
        ),
        UniqueConstraint(
            "tenant_id",
            "quote_draft_id",
            "position",
            name="uq_public_quote_draft_items_position",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "quote_draft_id"],
            ["public_quote_drafts.tenant_id", "public_quote_drafts.id"],
            name="fk_public_quote_draft_items_tenant_draft",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_public_quote_draft_items_tenant_sku",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_public_quote_draft_items_tenant_draft",
            "tenant_id",
            "quote_draft_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    quote_draft_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    product_id_snapshot: Mapped[UUID] = mapped_column(nullable=False)
    product_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sku_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sku_code_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    description_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    specification_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_values_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT,
        default=dict,
        nullable=False,
    )
    category_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags_snapshot: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    image_url_snapshot: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    minimum_order_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_code_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    currency_snapshot: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)


class PublicQuoteDownloadTokenRow(AuditTimestampMixin, Base):
    __tablename__ = "public_quote_download_tokens"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="token_hash_sha256_length"),
        UniqueConstraint(
            "tenant_id", "id", name="uq_public_quote_download_tokens_tenant_identity"
        ),
        UniqueConstraint("token_hash", name="uq_public_quote_download_tokens_hash"),
        ForeignKeyConstraint(
            ["tenant_id", "quote_draft_id"],
            ["public_quote_drafts.tenant_id", "public_quote_drafts.id"],
            name="fk_public_quote_download_tokens_tenant_draft",
            ondelete="CASCADE",
        ),
        Index(
            "ix_public_quote_download_tokens_tenant_draft_expiry",
            "tenant_id",
            "quote_draft_id",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    quote_draft_id: Mapped[UUID] = mapped_column(nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    one_time: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
