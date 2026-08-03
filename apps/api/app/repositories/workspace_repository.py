from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..db_models import ImportJobRow, ReviewItemRow, SourceFileRow, SupplierRow
from ..product_center_models import SkuRow, SupplierPriceRow
from ..product_supplier_models import ProductImageRow, ProductRow, SupplierProductRow, SupplierScoreRow
from ..public_catalog_models import PublicCatalogOfferRow
from ..trade_flow_models import InquiryRow, QuotationRow


def dashboard_snapshot(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    tenant_scope: bool,
    start_of_day: datetime,
    now: datetime,
    import_limit: int,
) -> dict[str, object]:
    inquiry_filters = [InquiryRow.tenant_id == tenant_id]
    quotation_filters = [QuotationRow.tenant_id == tenant_id]
    if not tenant_scope:
        inquiry_filters.append(InquiryRow.owner_membership_id == membership_id)
        quotation_filters.append(QuotationRow.created_by_membership_id == membership_id)

    active_skus = int(session.scalar(select(func.count()).select_from(SkuRow).where(SkuRow.tenant_id == tenant_id, SkuRow.status == "ACTIVE")) or 0)
    today_inquiries = int(session.scalar(select(func.count()).select_from(InquiryRow).where(*inquiry_filters, InquiryRow.created_at >= start_of_day)) or 0)
    open_inquiries = int(session.scalar(select(func.count()).select_from(InquiryRow).where(*inquiry_filters, InquiryRow.status.not_in(("QUOTED", "CLOSED")))) or 0)
    pending_quotes = int(session.scalar(select(func.count()).select_from(QuotationRow).where(*quotation_filters, QuotationRow.status.in_(("CALCULATED", "NEEDS_APPROVAL")))) or 0)
    pending_reviews = int(session.scalar(select(func.count()).select_from(ReviewItemRow).where(ReviewItemRow.tenant_id == tenant_id, ReviewItemRow.status == "pending")) or 0)
    active_suppliers = int(session.scalar(select(func.count()).select_from(SupplierRow).where(SupplierRow.tenant_id == tenant_id, SupplierRow.status == "ACTIVE")) or 0)

    recent_imports = session.execute(
        select(ImportJobRow, SourceFileRow)
        .join(SourceFileRow, and_(SourceFileRow.tenant_id == ImportJobRow.tenant_id, SourceFileRow.id == ImportJobRow.source_file_id))
        .where(ImportJobRow.tenant_id == tenant_id)
        .order_by(ImportJobRow.created_at.desc())
        .limit(import_limit)
    ).all()

    active_products = int(session.scalar(select(func.count()).select_from(ProductRow).where(ProductRow.tenant_id == tenant_id, ProductRow.status == "ACTIVE")) or 0)
    approved_images = int(
        session.scalar(
            select(func.count(func.distinct(ProductImageRow.product_id)))
            .join(
                ProductRow,
                and_(
                    ProductRow.tenant_id == ProductImageRow.tenant_id,
                    ProductRow.id == ProductImageRow.product_id,
                ),
            )
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.approval_status == "APPROVED",
                ProductRow.status == "ACTIVE",
            )
        )
        or 0
    )
    sourced_products = int(
        session.scalar(
            select(func.count(func.distinct(SupplierProductRow.product_id)))
            .join(
                ProductRow,
                and_(
                    ProductRow.tenant_id == SupplierProductRow.tenant_id,
                    ProductRow.id == SupplierProductRow.product_id,
                ),
            )
            .where(
                SupplierProductRow.tenant_id == tenant_id,
                SupplierProductRow.status == "ACTIVE",
                ProductRow.status == "ACTIVE",
            )
        )
        or 0
    )
    priced_products = int(session.scalar(
        select(func.count(func.distinct(SkuRow.product_id)))
        .join(
            PublicCatalogOfferRow,
            and_(
                PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id,
                PublicCatalogOfferRow.sku_id == SkuRow.id,
            ),
        )
        .join(
            ProductRow,
            and_(
                ProductRow.tenant_id == SkuRow.tenant_id,
                ProductRow.id == SkuRow.product_id,
            ),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.status == "ACTIVE",
            ProductRow.status == "ACTIVE",
            PublicCatalogOfferRow.publication_status == "PUBLISHED",
            or_(
                PublicCatalogOfferRow.valid_from.is_(None),
                PublicCatalogOfferRow.valid_from <= now,
            ),
            or_(
                PublicCatalogOfferRow.valid_to.is_(None),
                PublicCatalogOfferRow.valid_to >= now,
            ),
        )
    ) or 0)
    return {
        "active_skus": active_skus,
        "today_inquiries": today_inquiries,
        "open_inquiries": open_inquiries,
        "pending_quotes": pending_quotes,
        "pending_reviews": pending_reviews,
        "active_suppliers": active_suppliers,
        "recent_imports": recent_imports,
        "active_products": active_products,
        "approved_images": approved_images,
        "sourced_products": sourced_products,
        "priced_products": priced_products,
    }


def list_supplier_rows(session: Session, *, tenant_id: UUID) -> list[SupplierRow]:
    return list(session.scalars(select(SupplierRow).where(SupplierRow.tenant_id == tenant_id).order_by(SupplierRow.updated_at.desc(), SupplierRow.id)))


def get_supplier_row(session: Session, *, tenant_id: UUID, supplier_id: str) -> SupplierRow | None:
    return session.scalar(select(SupplierRow).where(SupplierRow.tenant_id == tenant_id, SupplierRow.id == supplier_id))


def supplier_code_exists(session: Session, *, tenant_id: UUID, supplier_code: str) -> bool:
    return bool(
        session.scalar(
            select(func.count()).select_from(SupplierRow).where(
                SupplierRow.tenant_id == tenant_id,
                func.lower(SupplierRow.supplier_code) == supplier_code.casefold(),
            )
        )
    )


def supplier_name_exists(session: Session, *, tenant_id: UUID, name: str) -> bool:
    return bool(
        session.scalar(
            select(func.count()).select_from(SupplierRow).where(
                SupplierRow.tenant_id == tenant_id,
                func.lower(SupplierRow.name) == name.casefold(),
            )
        )
    )


def supplier_aggregate_maps(session: Session, *, tenant_id: UUID, now: datetime) -> dict[str, dict[str, object]]:
    product_counts = dict(session.execute(select(SupplierProductRow.supplier_id, func.count(func.distinct(SupplierProductRow.product_id))).where(SupplierProductRow.tenant_id == tenant_id, SupplierProductRow.status == "ACTIVE").group_by(SupplierProductRow.supplier_id)).all())
    sku_counts = dict(session.execute(select(SupplierProductRow.supplier_id, func.count(func.distinct(SupplierProductRow.sku_id))).where(SupplierProductRow.tenant_id == tenant_id, SupplierProductRow.status == "ACTIVE", SupplierProductRow.sku_id.is_not(None)).group_by(SupplierProductRow.supplier_id)).all())
    review_counts = dict(session.execute(select(ImportJobRow.supplier_id, func.count(ReviewItemRow.id)).join(ReviewItemRow, and_(ReviewItemRow.tenant_id == ImportJobRow.tenant_id, ReviewItemRow.job_id == ImportJobRow.id)).where(ImportJobRow.tenant_id == tenant_id, ImportJobRow.supplier_id.is_not(None), ReviewItemRow.status == "pending").group_by(ImportJobRow.supplier_id)).all())
    latest_imports = dict(session.execute(select(ImportJobRow.supplier_id, func.max(ImportJobRow.created_at)).where(ImportJobRow.tenant_id == tenant_id, ImportJobRow.supplier_id.is_not(None)).group_by(ImportJobRow.supplier_id)).all())
    valid_prices = dict(session.execute(select(SupplierProductRow.supplier_id, func.count(func.distinct(SupplierPriceRow.supplier_product_id))).join(SupplierPriceRow, and_(SupplierPriceRow.tenant_id == SupplierProductRow.tenant_id, SupplierPriceRow.supplier_product_id == SupplierProductRow.id)).where(SupplierProductRow.tenant_id == tenant_id, SupplierPriceRow.status == "CONFIRMED", SupplierPriceRow.valid_from <= now, or_(SupplierPriceRow.valid_to.is_(None), SupplierPriceRow.valid_to >= now)).group_by(SupplierProductRow.supplier_id)).all())
    expired_prices = dict(session.execute(select(SupplierProductRow.supplier_id, func.count(func.distinct(SupplierPriceRow.supplier_product_id))).join(SupplierPriceRow, and_(SupplierPriceRow.tenant_id == SupplierProductRow.tenant_id, SupplierPriceRow.supplier_product_id == SupplierProductRow.id)).where(SupplierProductRow.tenant_id == tenant_id, SupplierPriceRow.status == "CONFIRMED", SupplierPriceRow.valid_to.is_not(None), SupplierPriceRow.valid_to < now).group_by(SupplierProductRow.supplier_id)).all())
    scores: dict[str, SupplierScoreRow] = {}
    for score in session.scalars(select(SupplierScoreRow).where(SupplierScoreRow.tenant_id == tenant_id).order_by(SupplierScoreRow.calculated_at.desc())):
        scores.setdefault(score.supplier_id, score)
    return {"products": product_counts, "skus": sku_counts, "reviews": review_counts, "imports": latest_imports, "valid_prices": valid_prices, "expired_prices": expired_prices, "scores": scores}


def list_supplier_sources(session: Session, *, tenant_id: UUID, supplier_id: str, now: datetime, limit: int) -> list[tuple[SupplierProductRow, ProductRow, SupplierPriceRow | None]]:
    sources = list(session.execute(select(SupplierProductRow, ProductRow).join(ProductRow, and_(ProductRow.tenant_id == SupplierProductRow.tenant_id, ProductRow.id == SupplierProductRow.product_id)).where(SupplierProductRow.tenant_id == tenant_id, SupplierProductRow.supplier_id == supplier_id).order_by(SupplierProductRow.updated_at.desc()).limit(limit)).all())
    result: list[tuple[SupplierProductRow, ProductRow, SupplierPriceRow | None]] = []
    for source, product in sources:
        price = session.scalar(select(SupplierPriceRow).where(SupplierPriceRow.tenant_id == tenant_id, SupplierPriceRow.supplier_product_id == source.id, SupplierPriceRow.status == "CONFIRMED", SupplierPriceRow.valid_from <= now).order_by(SupplierPriceRow.valid_from.desc(), SupplierPriceRow.created_at.desc()).limit(1))
        result.append((source, product, price))
    return result


def list_supplier_imports(session: Session, *, tenant_id: UUID, supplier_id: str, limit: int) -> list[tuple[ImportJobRow, SourceFileRow]]:
    return list(session.execute(select(ImportJobRow, SourceFileRow).join(SourceFileRow, and_(SourceFileRow.tenant_id == ImportJobRow.tenant_id, SourceFileRow.id == ImportJobRow.source_file_id)).where(ImportJobRow.tenant_id == tenant_id, ImportJobRow.supplier_id == supplier_id).order_by(ImportJobRow.created_at.desc()).limit(limit)).all())
