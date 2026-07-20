from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .ai_data_models import JSON_DOCUMENT
from .database import Base
from .model_mixins import AuditTimestampMixin


class CustomerRow(AuditTimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (CheckConstraint("status IN ('PROSPECT', 'ACTIVE', 'INACTIVE', 'ARCHIVED')", name="status_allowed"), UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_identity"), UniqueConstraint("tenant_id", "customer_code", name="uq_customers_tenant_code"), Index("ix_customers_tenant_name", "tenant_id", "company_name"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False)
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PROSPECT", nullable=False)


class InquiryRow(AuditTimestampMixin, Base):
    __tablename__ = "inquiries"
    __table_args__ = (CheckConstraint("status IN ('DRAFT', 'NEEDS_REVIEW', 'MATCHING', 'NEEDS_SELECTION', 'READY_FOR_QUOTE', 'QUOTED', 'CLOSED')", name="status_allowed"), CheckConstraint("version >= 1", name="version_positive"), CheckConstraint("customer_id IS NOT NULL OR temporary_customer_name IS NOT NULL", name="customer_context_required"), UniqueConstraint("tenant_id", "id", name="uq_inquiries_tenant_identity"), UniqueConstraint("tenant_id", "inquiry_number", name="uq_inquiries_tenant_number"), ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"], name="fk_inquiries_tenant_customer", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "owner_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_inquiries_tenant_owner", ondelete="RESTRICT"), Index("ix_inquiries_tenant_status_updated", "tenant_id", "status", "updated_at"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    inquiry_number: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(nullable=True)
    temporary_customer_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    owner_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class InquiryItemRow(AuditTimestampMixin, Base):
    __tablename__ = "inquiry_items"
    __table_args__ = (CheckConstraint("line_number >= 1", name="line_number_positive"), CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"), CheckConstraint("version >= 1", name="version_positive"), CheckConstraint("status IN ('DRAFT', 'CONFIRMED', 'MATCHED', 'SELECTED', 'NO_MATCH')", name="status_allowed"), UniqueConstraint("tenant_id", "id", name="uq_inquiry_items_tenant_identity"), UniqueConstraint("tenant_id", "inquiry_id", "line_number", name="uq_inquiry_items_line"), ForeignKeyConstraint(["tenant_id", "inquiry_id"], ["inquiries.tenant_id", "inquiries.id"], name="fk_inquiry_items_tenant_inquiry", ondelete="CASCADE"), ForeignKeyConstraint(["tenant_id", "image_search_id"], ["image_searches.tenant_id", "image_searches.id"], name="fk_inquiry_items_tenant_image_search", ondelete="RESTRICT"), Index("ix_inquiry_items_tenant_inquiry_status", "tenant_id", "inquiry_id", "status"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    inquiry_id: Mapped[UUID] = mapped_column(nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    raw_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_requirement: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    target_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    image_search_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_evidence_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class InquiryMatchResultRow(AuditTimestampMixin, Base):
    __tablename__ = "inquiry_match_results"
    __table_args__ = (CheckConstraint("rank >= 1", name="rank_positive"), CheckConstraint("total_score >= 0 AND total_score <= 1", name="total_score_range"), CheckConstraint("product_version >= 1", name="product_version_positive"), CheckConstraint("status IN ('CANDIDATE', 'SELECTED', 'REJECTED')", name="status_allowed"), UniqueConstraint("tenant_id", "id", name="uq_inquiry_match_results_tenant_identity"), UniqueConstraint("tenant_id", "inquiry_item_id", "ranking_version", "rank", name="uq_inquiry_match_results_rank"), ForeignKeyConstraint(["tenant_id", "inquiry_item_id"], ["inquiry_items.tenant_id", "inquiry_items.id"], name="fk_inquiry_match_results_tenant_item", ondelete="CASCADE"), ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_inquiry_match_results_tenant_product", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "sku_id"], ["skus.tenant_id", "skus.id"], name="fk_inquiry_match_results_tenant_sku", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "supplier_product_id"], ["supplier_products.tenant_id", "supplier_products.id"], name="fk_inquiry_match_results_tenant_source", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "selected_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_inquiry_match_results_tenant_selector", ondelete="RESTRICT"), Index("ix_inquiry_match_results_tenant_item_status", "tenant_id", "inquiry_item_id", "status"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    inquiry_item_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID | None] = mapped_column(nullable=True)
    supplier_product_id: Mapped[UUID | None] = mapped_column(nullable=True)
    product_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rank: Mapped[int] = mapped_column(nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    gaps: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    ranking_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="CANDIDATE", nullable=False)
    selected_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuotationRow(AuditTimestampMixin, Base):
    __tablename__ = "quotations"
    __table_args__ = (CheckConstraint("status IN ('DRAFT', 'CALCULATED', 'NEEDS_APPROVAL', 'APPROVED', 'SENT', 'ACCEPTED', 'REJECTED', 'EXPIRED')", name="status_allowed"), CheckConstraint("current_version >= 1", name="current_version_positive"), CheckConstraint("total_amount >= 0", name="total_amount_nonnegative"), UniqueConstraint("tenant_id", "id", name="uq_quotations_tenant_identity"), UniqueConstraint("tenant_id", "quotation_number", name="uq_quotations_tenant_number"), ForeignKeyConstraint(["tenant_id", "inquiry_id"], ["inquiries.tenant_id", "inquiries.id"], name="fk_quotations_tenant_inquiry", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"], name="fk_quotations_tenant_customer", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_quotations_tenant_creator", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "approved_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_quotations_tenant_approver", ondelete="RESTRICT"), Index("ix_quotations_tenant_status_updated", "tenant_id", "status", "updated_at"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    quotation_number: Mapped[str] = mapped_column(String(80), nullable=False)
    inquiry_id: Mapped[UUID] = mapped_column(nullable=False)
    customer_id: Mapped[UUID] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    current_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    approved_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QuotationVersionRow(AuditTimestampMixin, Base):
    __tablename__ = "quotation_versions"
    __table_args__ = (CheckConstraint("version_number >= 1", name="version_number_positive"), CheckConstraint("total_amount >= 0", name="total_amount_nonnegative"), UniqueConstraint("tenant_id", "id", name="uq_quotation_versions_tenant_identity"), UniqueConstraint("tenant_id", "quotation_id", "version_number", name="uq_quotation_versions_number"), UniqueConstraint("tenant_id", "quotation_id", "content_hash", name="uq_quotation_versions_hash"), ForeignKeyConstraint(["tenant_id", "quotation_id"], ["quotations.tenant_id", "quotations.id"], name="fk_quotation_versions_tenant_quotation", ondelete="CASCADE"), ForeignKeyConstraint(["tenant_id", "created_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_quotation_versions_tenant_creator", ondelete="RESTRICT"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    quotation_id: Mapped[UUID] = mapped_column(nullable=False)
    version_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)


class QuotationItemRow(AuditTimestampMixin, Base):
    __tablename__ = "quotation_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"), CheckConstraint("unit_cost >= 0 AND unit_price >= 0 AND line_total >= 0", name="amounts_nonnegative"), CheckConstraint("target_margin_rate >= 0 AND target_margin_rate < 1", name="margin_range"), UniqueConstraint("tenant_id", "id", name="uq_quotation_items_tenant_identity"), UniqueConstraint("tenant_id", "quotation_version_id", "inquiry_item_id", name="uq_quotation_items_version_line"), ForeignKeyConstraint(["tenant_id", "quotation_version_id"], ["quotation_versions.tenant_id", "quotation_versions.id"], name="fk_quotation_items_tenant_version", ondelete="CASCADE"), ForeignKeyConstraint(["tenant_id", "inquiry_item_id"], ["inquiry_items.tenant_id", "inquiry_items.id"], name="fk_quotation_items_tenant_inquiry_item", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_quotation_items_tenant_product", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "sku_id"], ["skus.tenant_id", "skus.id"], name="fk_quotation_items_tenant_sku", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "supplier_product_id"], ["supplier_products.tenant_id", "supplier_products.id"], name="fk_quotation_items_tenant_source", ondelete="RESTRICT"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    quotation_version_id: Mapped[UUID] = mapped_column(nullable=False)
    inquiry_item_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    sku_id: Mapped[UUID | None] = mapped_column(nullable=True)
    supplier_product_id: Mapped[UUID] = mapped_column(nullable=False)
    product_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    target_margin_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)


class QuotationApprovalRow(AuditTimestampMixin, Base):
    __tablename__ = "quotation_approvals"
    __table_args__ = (CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="status_allowed"), UniqueConstraint("tenant_id", "id", name="uq_quotation_approvals_tenant_identity"), UniqueConstraint("tenant_id", "quotation_version_id", name="uq_quotation_approvals_version"), ForeignKeyConstraint(["tenant_id", "quotation_id"], ["quotations.tenant_id", "quotations.id"], name="fk_quotation_approvals_tenant_quotation", ondelete="CASCADE"), ForeignKeyConstraint(["tenant_id", "quotation_version_id"], ["quotation_versions.tenant_id", "quotation_versions.id"], name="fk_quotation_approvals_tenant_version", ondelete="CASCADE"), ForeignKeyConstraint(["tenant_id", "requested_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_quotation_approvals_tenant_requester", ondelete="RESTRICT"), ForeignKeyConstraint(["tenant_id", "decided_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_quotation_approvals_tenant_decider", ondelete="RESTRICT"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    quotation_id: Mapped[UUID] = mapped_column(nullable=False)
    quotation_version_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    decided_by_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
