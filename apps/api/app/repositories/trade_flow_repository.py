from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..image_intelligence_models import ImageSearchRow
from ..product_center_models import SkuRow, SupplierPriceRow
from ..product_supplier_models import ProductRow, SupplierProductRow
from ..trade_flow_models import CustomerRow, InquiryItemRow, InquiryMatchResultRow, InquiryRow, QuotationApprovalRow, QuotationItemRow, QuotationRow, QuotationVersionRow


def get_customer(session: Session, *, tenant_id: UUID, customer_id: UUID) -> CustomerRow | None:
    return session.scalar(select(CustomerRow).where(CustomerRow.tenant_id == tenant_id, CustomerRow.id == customer_id, CustomerRow.deleted_at.is_(None)))


def get_inquiry(session: Session, *, tenant_id: UUID, inquiry_id: UUID) -> InquiryRow | None:
    return session.scalar(select(InquiryRow).where(InquiryRow.tenant_id == tenant_id, InquiryRow.id == inquiry_id, InquiryRow.deleted_at.is_(None)))


def list_inquiry_items(session: Session, *, tenant_id: UUID, inquiry_id: UUID) -> list[InquiryItemRow]:
    return session.scalars(select(InquiryItemRow).where(InquiryItemRow.tenant_id == tenant_id, InquiryItemRow.inquiry_id == inquiry_id, InquiryItemRow.deleted_at.is_(None)).order_by(InquiryItemRow.line_number)).all()


def get_inquiry_item(session: Session, *, tenant_id: UUID, item_id: UUID) -> InquiryItemRow | None:
    return session.scalar(select(InquiryItemRow).where(InquiryItemRow.tenant_id == tenant_id, InquiryItemRow.id == item_id, InquiryItemRow.deleted_at.is_(None)))


def find_exact_products(session: Session, *, tenant_id: UUID, query: str, limit: int = 10) -> list[ProductRow]:
    normalized = query.strip()
    sku_product_ids = select(SkuRow.product_id).where(
        SkuRow.tenant_id == tenant_id,
        or_(
            func.lower(SkuRow.sku_code) == normalized.lower(),
            func.lower(func.coalesce(SkuRow.source_sku_code, ""))
            == normalized.lower(),
        ),
        SkuRow.deleted_at.is_(None),
    )
    return session.scalars(select(ProductRow).where(ProductRow.tenant_id == tenant_id, ProductRow.status == "ACTIVE", ProductRow.deleted_at.is_(None), or_(func.lower(ProductRow.product_code) == normalized.lower(), func.lower(ProductRow.name).contains(normalized.lower()), ProductRow.id.in_(sku_product_ids))).limit(limit)).all()


def get_product(session: Session, *, tenant_id: UUID, product_id: UUID) -> ProductRow | None:
    return session.scalar(select(ProductRow).where(ProductRow.tenant_id == tenant_id, ProductRow.id == product_id, ProductRow.deleted_at.is_(None)))


def first_sku(session: Session, *, tenant_id: UUID, product_id: UUID) -> SkuRow | None:
    return session.scalar(select(SkuRow).where(SkuRow.tenant_id == tenant_id, SkuRow.product_id == product_id, SkuRow.status.in_(("ACTIVE", "DRAFT")), SkuRow.deleted_at.is_(None)).order_by(SkuRow.status, SkuRow.created_at))


def first_source(session: Session, *, tenant_id: UUID, product_id: UUID) -> SupplierProductRow | None:
    return session.scalar(select(SupplierProductRow).where(SupplierProductRow.tenant_id == tenant_id, SupplierProductRow.product_id == product_id, SupplierProductRow.status == "ACTIVE", SupplierProductRow.deleted_at.is_(None)).order_by(SupplierProductRow.created_at))


def get_active_source(session: Session, *, tenant_id: UUID, product_id: UUID, source_id: UUID) -> SupplierProductRow | None:
    return session.scalar(select(SupplierProductRow).where(SupplierProductRow.tenant_id == tenant_id, SupplierProductRow.id == source_id, SupplierProductRow.product_id == product_id, SupplierProductRow.status == "ACTIVE", SupplierProductRow.deleted_at.is_(None)))


def get_image_search(session: Session, *, tenant_id: UUID, search_id: UUID) -> ImageSearchRow | None:
    return session.scalar(select(ImageSearchRow).where(ImageSearchRow.tenant_id == tenant_id, ImageSearchRow.id == search_id, ImageSearchRow.deleted_at.is_(None)))


def list_candidates(session: Session, *, tenant_id: UUID, item_id: UUID, ranking_version: str | None = None) -> list[InquiryMatchResultRow]:
    statement = select(InquiryMatchResultRow).where(InquiryMatchResultRow.tenant_id == tenant_id, InquiryMatchResultRow.inquiry_item_id == item_id, InquiryMatchResultRow.deleted_at.is_(None))
    if ranking_version:
        statement = statement.where(InquiryMatchResultRow.ranking_version == ranking_version)
    return session.scalars(statement.order_by(InquiryMatchResultRow.created_at.desc(), InquiryMatchResultRow.rank)).all()


def get_match(session: Session, *, tenant_id: UUID, match_id: UUID) -> InquiryMatchResultRow | None:
    return session.scalar(select(InquiryMatchResultRow).where(InquiryMatchResultRow.tenant_id == tenant_id, InquiryMatchResultRow.id == match_id, InquiryMatchResultRow.deleted_at.is_(None)))


def selected_match(session: Session, *, tenant_id: UUID, item_id: UUID) -> InquiryMatchResultRow | None:
    return session.scalar(select(InquiryMatchResultRow).where(InquiryMatchResultRow.tenant_id == tenant_id, InquiryMatchResultRow.inquiry_item_id == item_id, InquiryMatchResultRow.status == "SELECTED", InquiryMatchResultRow.deleted_at.is_(None)).order_by(InquiryMatchResultRow.selected_at.desc()))


def current_price(session: Session, *, tenant_id: UUID, source_id: UUID, sku_id: UUID | None, as_of: datetime) -> SupplierPriceRow | None:
    statement = select(SupplierPriceRow).where(SupplierPriceRow.tenant_id == tenant_id, SupplierPriceRow.supplier_product_id == source_id, SupplierPriceRow.status == "CONFIRMED", SupplierPriceRow.valid_from <= as_of, SupplierPriceRow.deleted_at.is_(None))
    if sku_id:
        statement = statement.where(or_(SupplierPriceRow.sku_id == sku_id, SupplierPriceRow.sku_id.is_(None)))
    return session.scalar(statement.order_by(SupplierPriceRow.valid_from.desc(), SupplierPriceRow.created_at.desc()))


def list_quotations(session: Session, *, tenant_id: UUID, limit: int) -> list[tuple[QuotationRow, CustomerRow]]:
    return session.execute(select(QuotationRow, CustomerRow).join(CustomerRow, (CustomerRow.tenant_id == QuotationRow.tenant_id) & (CustomerRow.id == QuotationRow.customer_id)).where(QuotationRow.tenant_id == tenant_id, QuotationRow.deleted_at.is_(None)).order_by(QuotationRow.updated_at.desc()).limit(limit)).all()


def get_quotation(session: Session, *, tenant_id: UUID, quotation_id: UUID) -> tuple[QuotationRow, QuotationVersionRow, QuotationApprovalRow] | None:
    return session.execute(select(QuotationRow, QuotationVersionRow, QuotationApprovalRow).join(QuotationVersionRow, (QuotationVersionRow.tenant_id == QuotationRow.tenant_id) & (QuotationVersionRow.quotation_id == QuotationRow.id) & (QuotationVersionRow.version_number == QuotationRow.current_version)).join(QuotationApprovalRow, (QuotationApprovalRow.tenant_id == QuotationVersionRow.tenant_id) & (QuotationApprovalRow.quotation_version_id == QuotationVersionRow.id)).where(QuotationRow.tenant_id == tenant_id, QuotationRow.id == quotation_id, QuotationRow.deleted_at.is_(None))).one_or_none()


def get_quotation_for_update(session: Session, *, tenant_id: UUID, quotation_id: UUID) -> tuple[QuotationRow, QuotationVersionRow, QuotationApprovalRow] | None:
    return session.execute(select(QuotationRow, QuotationVersionRow, QuotationApprovalRow).join(QuotationVersionRow, (QuotationVersionRow.tenant_id == QuotationRow.tenant_id) & (QuotationVersionRow.quotation_id == QuotationRow.id) & (QuotationVersionRow.version_number == QuotationRow.current_version)).join(QuotationApprovalRow, (QuotationApprovalRow.tenant_id == QuotationVersionRow.tenant_id) & (QuotationApprovalRow.quotation_version_id == QuotationVersionRow.id)).where(QuotationRow.tenant_id == tenant_id, QuotationRow.id == quotation_id, QuotationRow.deleted_at.is_(None)).with_for_update(of=QuotationRow)).one_or_none()


def list_quotation_versions(session: Session, *, tenant_id: UUID, quotation_id: UUID) -> list[tuple[QuotationVersionRow, QuotationApprovalRow]]:
    return list(session.execute(select(QuotationVersionRow, QuotationApprovalRow).join(QuotationApprovalRow, (QuotationApprovalRow.tenant_id == QuotationVersionRow.tenant_id) & (QuotationApprovalRow.quotation_version_id == QuotationVersionRow.id)).where(QuotationVersionRow.tenant_id == tenant_id, QuotationVersionRow.quotation_id == quotation_id).order_by(QuotationVersionRow.version_number.desc())).all())


def list_quote_items(session: Session, *, tenant_id: UUID, version_id: UUID) -> list[QuotationItemRow]:
    return session.scalars(select(QuotationItemRow).where(QuotationItemRow.tenant_id == tenant_id, QuotationItemRow.quotation_version_id == version_id, QuotationItemRow.deleted_at.is_(None)).order_by(QuotationItemRow.created_at)).all()
