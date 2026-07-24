from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db_models import SupplierRow
from ..domain.errors import ApplicationError
from ..repositories import workspace_repository as repository
from ..workspace_schemas import (
    DashboardDataHealth,
    DashboardImport,
    DashboardMetric,
    DashboardResponse,
    SupplierImportSummary,
    SupplierCreateRequest,
    SupplierProfileDetail,
    SupplierProfileSummary,
    SupplierScoreSummary,
    SupplierSourceSummary,
)


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError("PERMISSION_DENIED", f"Missing required permission: {code}", kind="forbidden")


def _require_any(permissions: frozenset[str], *codes: str) -> None:
    if not permissions.intersection(codes):
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Missing one of the required permissions: {', '.join(codes)}",
            kind="forbidden",
        )


def get_dashboard(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    import_limit: int,
) -> DashboardResponse:
    now = datetime.now(UTC)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=UTC)
    tenant_scope = bool({"system.user_manage", "supplier.manage", "quotation.approve"} & permissions)
    data = repository.dashboard_snapshot(
        session,
        tenant_id=tenant_id,
        membership_id=membership_id,
        tenant_scope=tenant_scope,
        start_of_day=start_of_day,
        now=now,
        import_limit=import_limit,
    )
    metrics: list[DashboardMetric] = []
    if "product.view" in permissions:
        metrics.append(DashboardMetric(key="active_skus", label="有效 SKU", value=data["active_skus"], destination="/products"))
    if "inquiry.view" in permissions:
        metrics.extend((
            DashboardMetric(key="today_inquiries", label="今日询盘", value=data["today_inquiries"], destination="/inquiries"),
            DashboardMetric(key="open_inquiries", label="待处理询盘", value=data["open_inquiries"], destination="/inquiries"),
        ))
    if "quotation.view" in permissions:
        metrics.append(DashboardMetric(key="pending_quotations", label="待确认报价", value=data["pending_quotes"], destination="/quotations"))
    if "product.review" in permissions:
        metrics.append(DashboardMetric(key="pending_product_reviews", label="等待复核", value=data["pending_reviews"], destination="/review"))
    if "supplier.view" in permissions:
        metrics.append(DashboardMetric(key="active_suppliers", label="有效供应商", value=data["active_suppliers"], destination="/suppliers"))

    active_products = int(data["active_products"])
    data_health = None
    if "product.view" in permissions:
        def coverage(value: object) -> float:
            return round(int(value) / active_products, 4) if active_products else 0.0

        image_coverage = coverage(data["approved_images"])
        source_coverage = coverage(data["sourced_products"])
        price_coverage = coverage(data["priced_products"])
        data_health = DashboardDataHealth(
            # Supplier linkage is optional in the fixed-template architecture,
            # so it must not lower the merchant's product-data health score.
            score=round((image_coverage + price_coverage) / 2 * 100),
            active_products=active_products,
            approved_image_coverage=image_coverage,
            supplier_source_coverage=source_coverage,
            valid_price_coverage=price_coverage,
        )
    recent_imports = [
        DashboardImport(
            id=job.id,
            filename=source.original_filename,
            source_type=job.source_type,
            supplier_name=job.supplier_name,
            status=job.status,
            progress=job.progress,
            products_count=job.products_count,
            warnings_count=job.warnings_count,
            created_at=job.created_at,
        )
        for job, source in data["recent_imports"]
    ] if "product.import" in permissions else []
    return DashboardResponse(
        generated_at=now,
        data_scope="TENANT" if tenant_scope else "SELF",
        metrics=metrics,
        recent_imports=recent_imports,
        data_health=data_health,
    )


def _score(row: object | None) -> SupplierScoreSummary | None:
    if row is None:
        return None
    return SupplierScoreSummary(
        overall_score=row.overall_score,
        quality_score=row.quality_score,
        price_score=row.price_score,
        delivery_score=row.delivery_score,
        response_score=row.response_score,
        risk_score=row.risk_score,
        sample_size=row.sample_size,
        method_version=row.method_version,
        calculated_at=row.calculated_at,
    )


def _supplier_summary(row: object, maps: dict[str, dict[str, object]]) -> SupplierProfileSummary:
    return SupplierProfileSummary(
        id=row.id,
        supplier_code=row.supplier_code,
        name=row.name,
        category=row.category,
        category_summary=row.category_summary,
        country_code=row.country_code,
        website=row.website,
        status=row.status,
        risk_level=row.risk_level,
        health=row.health,
        version=row.version,
        active_products=int(maps["products"].get(row.id, 0)),
        active_skus=int(maps["skus"].get(row.id, 0)),
        pending_reviews=int(maps["reviews"].get(row.id, 0)),
        valid_prices=int(maps["valid_prices"].get(row.id, 0)),
        expired_prices=int(maps["expired_prices"].get(row.id, 0)),
        latest_import_at=maps["imports"].get(row.id),
        updated_at=row.updated_at,
        latest_score=_score(maps["scores"].get(row.id)),
    )


def list_suppliers(session: Session, *, tenant_id: UUID, permissions: frozenset[str]) -> list[SupplierProfileSummary]:
    _require_any(permissions, "supplier.view", "supplier.manage")
    now = datetime.now(UTC)
    maps = repository.supplier_aggregate_maps(session, tenant_id=tenant_id, now=now)
    return [_supplier_summary(row, maps) for row in repository.list_supplier_rows(session, tenant_id=tenant_id)]


def create_supplier(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: SupplierCreateRequest,
) -> SupplierProfileSummary:
    _require(permissions, "supplier.manage")
    if repository.supplier_code_exists(
        session, tenant_id=tenant_id, supplier_code=request.supplier_code
    ):
        raise ApplicationError(
            "SUPPLIER_CODE_CONFLICT",
            "Supplier code already exists in this tenant.",
            kind="conflict",
        )
    if repository.supplier_name_exists(session, tenant_id=tenant_id, name=request.name):
        raise ApplicationError(
            "SUPPLIER_NAME_CONFLICT",
            "Supplier name already exists in this tenant.",
            kind="conflict",
        )
    row = SupplierRow(
        id=f"SUP-{uuid4().hex[:12].upper()}",
        tenant_id=tenant_id,
        supplier_code=request.supplier_code,
        name=request.name,
        category=request.category,
        category_summary=request.category,
        country_code=request.country_code,
        website=request.website,
        status="ACTIVE",
        risk_level="UNKNOWN",
        health="good",
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPLIER_CODE_CONFLICT",
            "Supplier code already exists in this tenant.",
            kind="conflict",
        ) from exc
    session.refresh(row)
    maps = repository.supplier_aggregate_maps(
        session, tenant_id=tenant_id, now=datetime.now(UTC)
    )
    return _supplier_summary(row, maps)


def get_supplier(session: Session, *, tenant_id: UUID, permissions: frozenset[str], supplier_id: str) -> SupplierProfileDetail:
    _require_any(permissions, "supplier.view", "supplier.manage")
    row = repository.get_supplier_row(session, tenant_id=tenant_id, supplier_id=supplier_id)
    if row is None:
        raise ApplicationError("SUPPLIER_NOT_FOUND", "Supplier was not found.", kind="not_found")
    now = datetime.now(UTC)
    maps = repository.supplier_aggregate_maps(session, tenant_id=tenant_id, now=now)
    summary = _supplier_summary(row, maps)
    sources: list[SupplierSourceSummary] = []
    for source, product, price in repository.list_supplier_sources(session, tenant_id=tenant_id, supplier_id=supplier_id, now=now, limit=100):
        valid_to = price.valid_to if price else None
        if valid_to is not None and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=UTC)
        price_validity = "UNKNOWN"
        if price is not None:
            price_validity = "EXPIRED" if valid_to is not None and valid_to < now else "VALID"
        sources.append(SupplierSourceSummary(
            supplier_product_id=source.id,
            product_id=product.id,
            product_code=product.product_code,
            product_name=product.name,
            sku_id=source.sku_id,
            supplier_sku=source.supplier_sku,
            moq=source.moq,
            moq_unit=source.moq_unit,
            lead_time_days=source.lead_time_days,
            status=source.status,
            unit_price=price.unit_price if price else None,
            currency=price.currency if price else None,
            price_valid_to=valid_to,
            price_validity=price_validity,
        ))
    imports = [
        SupplierImportSummary(
            id=job.id,
            filename=source.original_filename,
            status=job.status,
            products_count=job.products_count,
            warnings_count=job.warnings_count,
            created_at=job.created_at,
        )
        for job, source in repository.list_supplier_imports(session, tenant_id=tenant_id, supplier_id=supplier_id, limit=20)
    ]
    return SupplierProfileDetail(**summary.model_dump(), sources=sources, recent_imports=imports)
