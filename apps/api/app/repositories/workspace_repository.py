from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, union
from sqlalchemy.orm import Session

from ..dashboard_models import DashboardStatisticsRow
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
    # ``import_limit`` remains in the function signature for clients that
    # still send it, but imports are deliberately not part of the overview
    # read model anymore.  Product provenance remains on each SKU/import row.
    del import_limit
    row = session.scalar(
        select(DashboardStatisticsRow).where(
            DashboardStatisticsRow.tenant_id == tenant_id,
        )
    )
    if (
        row is None
        or row.is_dirty
        or row.statistics_date != now.date()
    ):
        row = refresh_dashboard_statistics(
            session,
            tenant_id=tenant_id,
            start_of_day=start_of_day,
            now=now,
            existing=row,
        )

    membership_metrics = row.membership_metrics or {}
    member_metrics = membership_metrics.get(str(membership_id), {})
    return {
        "active_skus": int(row.active_skus or 0),
        "today_inquiries": int(
            row.today_inquiries if tenant_scope else member_metrics.get("today_inquiries", 0)
        ),
        "open_inquiries": int(
            row.open_inquiries if tenant_scope else member_metrics.get("open_inquiries", 0)
        ),
        "pending_quotes": int(
            row.pending_quotes if tenant_scope else member_metrics.get("pending_quotes", 0)
        ),
        "pending_reviews": int(row.pending_reviews or 0),
        "active_suppliers": int(row.active_suppliers or 0),
        # Keep the raw health counters in the read model for future reporting;
        # the current overview no longer renders a "data completeness" panel.
        "active_products": int(row.active_products or 0),
        "approved_images": int(row.approved_images or 0),
        "sourced_products": int(row.sourced_products or 0),
        "priced_products": int(row.priced_products or 0),
        "recent_imports": [],
    }


def _grouped_member_counts(
    session: Session,
    *,
    tenant_id: UUID,
    start_of_day: datetime,
) -> dict[str, dict[str, int]]:
    """Build the small per-membership portion of the dashboard read model."""

    today_rows = session.execute(
        select(InquiryRow.owner_membership_id, func.count())
        .where(
            InquiryRow.tenant_id == tenant_id,
            InquiryRow.created_at >= start_of_day,
        )
        .group_by(InquiryRow.owner_membership_id)
    ).all()
    open_rows = session.execute(
        select(InquiryRow.owner_membership_id, func.count())
        .where(
            InquiryRow.tenant_id == tenant_id,
            InquiryRow.status.not_in(("QUOTED", "CLOSED")),
        )
        .group_by(InquiryRow.owner_membership_id)
    ).all()
    quote_rows = session.execute(
        select(QuotationRow.created_by_membership_id, func.count())
        .where(
            QuotationRow.tenant_id == tenant_id,
            QuotationRow.status.in_(("CALCULATED", "NEEDS_APPROVAL")),
        )
        .group_by(QuotationRow.created_by_membership_id)
    ).all()
    result: dict[str, dict[str, int]] = {}
    for membership_id, count in today_rows:
        result.setdefault(str(membership_id), {})["today_inquiries"] = int(count)
    for membership_id, count in open_rows:
        result.setdefault(str(membership_id), {})["open_inquiries"] = int(count)
    for membership_id, count in quote_rows:
        result.setdefault(str(membership_id), {})["pending_quotes"] = int(count)
    return result


def refresh_dashboard_statistics(
    session: Session,
    *,
    tenant_id: UUID,
    start_of_day: datetime,
    now: datetime,
    existing: DashboardStatisticsRow | None = None,
) -> DashboardStatisticsRow:
    """Rebuild one tenant's dashboard read model after it becomes dirty."""

    row = existing or session.scalar(
        select(DashboardStatisticsRow).where(
            DashboardStatisticsRow.tenant_id == tenant_id,
        )
    )
    if row is None:
        row = DashboardStatisticsRow(tenant_id=tenant_id)
        session.add(row)

    row.active_skus = int(
        session.scalar(
            select(func.count())
            .select_from(SkuRow)
            .where(SkuRow.tenant_id == tenant_id, SkuRow.status == "ACTIVE")
        )
        or 0
    )
    row.active_products = int(
        session.scalar(
            select(func.count())
            .select_from(ProductRow)
            .where(ProductRow.tenant_id == tenant_id, ProductRow.status == "ACTIVE")
        )
        or 0
    )
    row.active_suppliers = int(
        session.scalar(
            select(func.count())
            .select_from(SupplierRow)
            .where(SupplierRow.tenant_id == tenant_id, SupplierRow.status == "ACTIVE")
        )
        or 0
    )
    row.today_inquiries = int(
        session.scalar(
            select(func.count())
            .select_from(InquiryRow)
            .where(
                InquiryRow.tenant_id == tenant_id,
                InquiryRow.created_at >= start_of_day,
            )
        )
        or 0
    )
    row.open_inquiries = int(
        session.scalar(
            select(func.count())
            .select_from(InquiryRow)
            .where(
                InquiryRow.tenant_id == tenant_id,
                InquiryRow.status.not_in(("QUOTED", "CLOSED")),
            )
        )
        or 0
    )
    row.pending_quotes = int(
        session.scalar(
            select(func.count())
            .select_from(QuotationRow)
            .where(
                QuotationRow.tenant_id == tenant_id,
                QuotationRow.status.in_(("CALCULATED", "NEEDS_APPROVAL")),
            )
        )
        or 0
    )
    row.pending_reviews = int(
        session.scalar(
            select(func.count())
            .select_from(ReviewItemRow)
            .where(
                ReviewItemRow.tenant_id == tenant_id,
                ReviewItemRow.status == "pending",
            )
        )
        or 0
    )
    row.approved_images = int(
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
    row.sourced_products = int(
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
    row.priced_products = int(
        session.scalar(
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
        )
        or 0
    )
    row.statistics_date = now.date()
    row.refreshed_at = now
    row.is_dirty = False
    row.membership_metrics = _grouped_member_counts(
        session,
        tenant_id=tenant_id,
        start_of_day=start_of_day,
    )
    session.flush()
    session.commit()
    return row


def list_supplier_rows(session: Session, *, tenant_id: UUID) -> list[SupplierRow]:
    return list(session.scalars(select(SupplierRow).where(SupplierRow.tenant_id == tenant_id).order_by(SupplierRow.updated_at.desc(), SupplierRow.id)))


def list_supply_chain_rows(
    session: Session,
    *,
    tenant_id: UUID,
    query: str | None,
    status: str | None,
    offset: int,
    limit: int,
) -> tuple[list[SupplierRow], int]:
    filters = [SupplierRow.tenant_id == tenant_id]
    normalized_query = " ".join((query or "").split()).casefold()
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                func.lower(SupplierRow.name).like(pattern),
                func.lower(SupplierRow.supplier_code).like(pattern),
                func.lower(func.coalesce(SupplierRow.contact_name, "")).like(pattern),
                func.lower(func.coalesce(SupplierRow.phone, "")).like(pattern),
                func.lower(func.coalesce(SupplierRow.email, "")).like(pattern),
                func.lower(func.coalesce(SupplierRow.country_region, "")).like(pattern),
            )
        )
    if status:
        filters.append(SupplierRow.status == status)
    total = int(
        session.scalar(
            select(func.count()).select_from(SupplierRow).where(*filters)
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(SupplierRow)
            .where(*filters)
            .order_by(SupplierRow.updated_at.desc(), SupplierRow.name, SupplierRow.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total


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


def supplier_name_exists(
    session: Session,
    *,
    tenant_id: UUID,
    name: str,
    exclude_supplier_id: str | None = None,
) -> bool:
    filters = [
        SupplierRow.tenant_id == tenant_id,
        func.lower(SupplierRow.name) == name.casefold(),
    ]
    if exclude_supplier_id is not None:
        filters.append(SupplierRow.id != exclude_supplier_id)
    return bool(
        session.scalar(
            select(func.count()).select_from(SupplierRow).where(*filters)
        )
    )


def supplier_aggregate_maps(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    supplier_ids: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    if supplier_ids is not None and not supplier_ids:
        return {
            "products": {},
            "skus": {},
            "reviews": {},
            "imports": {},
            "valid_prices": {},
            "expired_prices": {},
            "scores": {},
        }

    source_scope = (
        []
        if supplier_ids is None
        else [SupplierProductRow.supplier_id.in_(supplier_ids)]
    )
    import_scope = (
        [] if supplier_ids is None else [ImportJobRow.supplier_id.in_(supplier_ids)]
    )
    score_scope = (
        [] if supplier_ids is None else [SupplierScoreRow.supplier_id.in_(supplier_ids)]
    )
    # A supplier can be linked in two ways: an explicit SupplierProductRow
    # (supplier-catalog imports and AI adoption) or directly on SkuRow
    # (product-template imports). The old product aggregate only considered
    # the former, so a supplier with template-owned SKUs showed "0 products"
    # even though its SKU count was populated from the denormalized supplier
    # counter. Union both authoritative paths before counting to keep product
    # and SKU totals consistent and avoid double-counting mixed imports.
    supplier_product_links = select(
        SupplierProductRow.supplier_id.label("supplier_id"),
        SupplierProductRow.product_id.label("product_id"),
    ).where(
        SupplierProductRow.tenant_id == tenant_id,
        SupplierProductRow.status == "ACTIVE",
        SupplierProductRow.deleted_at.is_(None),
        *source_scope,
    )
    direct_sku_product_links = select(
        SkuRow.supplier_id.label("supplier_id"),
        SkuRow.product_id.label("product_id"),
    ).where(
        SkuRow.tenant_id == tenant_id,
        SkuRow.supplier_id.is_not(None),
        SkuRow.status == "ACTIVE",
        SkuRow.deleted_at.is_(None),
        *([] if supplier_ids is None else [SkuRow.supplier_id.in_(supplier_ids)]),
    )
    product_links = union(
        supplier_product_links,
        direct_sku_product_links,
    ).subquery()
    product_counts = dict(
        session.execute(
            select(
                product_links.c.supplier_id,
                func.count().label("product_count"),
            ).group_by(product_links.c.supplier_id)
        ).all()
    )

    supplier_product_sku_links = select(
        SupplierProductRow.supplier_id.label("supplier_id"),
        SupplierProductRow.sku_id.label("sku_id"),
    ).where(
        SupplierProductRow.tenant_id == tenant_id,
        SupplierProductRow.status == "ACTIVE",
        SupplierProductRow.deleted_at.is_(None),
        SupplierProductRow.sku_id.is_not(None),
        *source_scope,
    )
    direct_sku_links = select(
        SkuRow.supplier_id.label("supplier_id"),
        SkuRow.id.label("sku_id"),
    ).where(
        SkuRow.tenant_id == tenant_id,
        SkuRow.supplier_id.is_not(None),
        SkuRow.status == "ACTIVE",
        SkuRow.deleted_at.is_(None),
        *([] if supplier_ids is None else [SkuRow.supplier_id.in_(supplier_ids)]),
    )
    sku_links = union(
        supplier_product_sku_links,
        direct_sku_links,
    ).subquery()
    sku_counts = dict(
        session.execute(
            select(
                sku_links.c.supplier_id,
                func.count().label("sku_count"),
            ).group_by(sku_links.c.supplier_id)
        ).all()
    )
    review_counts = dict(
        session.execute(
            select(ImportJobRow.supplier_id, func.count(ReviewItemRow.id))
            .join(
                ReviewItemRow,
                and_(
                    ReviewItemRow.tenant_id == ImportJobRow.tenant_id,
                    ReviewItemRow.job_id == ImportJobRow.id,
                ),
            )
            .where(
                ImportJobRow.tenant_id == tenant_id,
                ImportJobRow.supplier_id.is_not(None),
                ReviewItemRow.status == "pending",
                *import_scope,
            )
            .group_by(ImportJobRow.supplier_id)
        ).all()
    )
    latest_imports = dict(
        session.execute(
            select(ImportJobRow.supplier_id, func.max(ImportJobRow.created_at))
            .where(
                ImportJobRow.tenant_id == tenant_id,
                ImportJobRow.supplier_id.is_not(None),
                *import_scope,
            )
            .group_by(ImportJobRow.supplier_id)
        ).all()
    )
    price_join = and_(
        SupplierPriceRow.tenant_id == SupplierProductRow.tenant_id,
        SupplierPriceRow.supplier_product_id == SupplierProductRow.id,
    )
    valid_prices = dict(
        session.execute(
            select(
                SupplierProductRow.supplier_id,
                func.count(func.distinct(SupplierPriceRow.supplier_product_id)),
            )
            .join(SupplierPriceRow, price_join)
            .where(
                SupplierProductRow.tenant_id == tenant_id,
                SupplierPriceRow.status == "CONFIRMED",
                SupplierPriceRow.valid_from <= now,
                or_(
                    SupplierPriceRow.valid_to.is_(None),
                    SupplierPriceRow.valid_to >= now,
                ),
                *source_scope,
            )
            .group_by(SupplierProductRow.supplier_id)
        ).all()
    )
    expired_prices = dict(
        session.execute(
            select(
                SupplierProductRow.supplier_id,
                func.count(func.distinct(SupplierPriceRow.supplier_product_id)),
            )
            .join(SupplierPriceRow, price_join)
            .where(
                SupplierProductRow.tenant_id == tenant_id,
                SupplierPriceRow.status == "CONFIRMED",
                SupplierPriceRow.valid_to.is_not(None),
                SupplierPriceRow.valid_to < now,
                *source_scope,
            )
            .group_by(SupplierProductRow.supplier_id)
        ).all()
    )
    scores: dict[str, SupplierScoreRow] = {}
    for score in session.scalars(
        select(SupplierScoreRow)
        .where(SupplierScoreRow.tenant_id == tenant_id, *score_scope)
        .order_by(SupplierScoreRow.calculated_at.desc())
    ):
        scores.setdefault(score.supplier_id, score)
    return {
        "products": product_counts,
        "skus": sku_counts,
        "reviews": review_counts,
        "imports": latest_imports,
        "valid_prices": valid_prices,
        "expired_prices": expired_prices,
        "scores": scores,
    }


def list_supplier_sources(session: Session, *, tenant_id: UUID, supplier_id: str, now: datetime, limit: int) -> list[tuple[SupplierProductRow, ProductRow, SupplierPriceRow | None]]:
    sources = list(session.execute(select(SupplierProductRow, ProductRow).join(ProductRow, and_(ProductRow.tenant_id == SupplierProductRow.tenant_id, ProductRow.id == SupplierProductRow.product_id)).where(SupplierProductRow.tenant_id == tenant_id, SupplierProductRow.supplier_id == supplier_id).order_by(SupplierProductRow.updated_at.desc()).limit(limit)).all())
    result: list[tuple[SupplierProductRow, ProductRow, SupplierPriceRow | None]] = []
    for source, product in sources:
        price = session.scalar(select(SupplierPriceRow).where(SupplierPriceRow.tenant_id == tenant_id, SupplierPriceRow.supplier_product_id == source.id, SupplierPriceRow.status == "CONFIRMED", SupplierPriceRow.valid_from <= now).order_by(SupplierPriceRow.valid_from.desc(), SupplierPriceRow.created_at.desc()).limit(1))
        result.append((source, product, price))
    return result


def list_supplier_imports(session: Session, *, tenant_id: UUID, supplier_id: str, limit: int) -> list[tuple[ImportJobRow, SourceFileRow]]:
    return list(session.execute(select(ImportJobRow, SourceFileRow).join(SourceFileRow, and_(SourceFileRow.tenant_id == ImportJobRow.tenant_id, SourceFileRow.id == ImportJobRow.source_file_id)).where(ImportJobRow.tenant_id == tenant_id, ImportJobRow.supplier_id == supplier_id).order_by(ImportJobRow.created_at.desc()).limit(limit)).all())
