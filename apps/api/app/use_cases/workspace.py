from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db_models import SupplierRow
from ..domain.errors import ApplicationError
from ..model_mixins import mark_deleted
from ..repositories import workspace_repository as repository
from ..services import query_cache
from ..workspace_schemas import (
    DashboardDataHealth,
    DashboardMetric,
    DashboardResponse,
    SupplyChainCreateRequest,
    SupplyChainPageResponse,
    SupplyChainUpdateRequest,
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
    cache_slot = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_DASHBOARD,
        identity={
            "kind": "dashboard",
            "membership_id": str(membership_id),
            "tenant_scope": tenant_scope,
            "permissions": sorted(permissions),
        },
    )
    if cache_slot.hit:
        try:
            return DashboardResponse.model_validate(cache_slot.value)
        except (TypeError, ValueError):
            pass
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
        metrics.append(DashboardMetric(key="active_suppliers", label="合作供应链", value=data["active_suppliers"], destination="/supply-chain"))

    active_products = int(data["active_products"])
    data_health = None
    if "product.view" in permissions:
        def coverage(value: object) -> float:
            if not active_products:
                return 0.0
            # Historical imports can leave auxiliary rows behind after a
            # product is archived. The repository scopes those rows to active
            # products, and this clamp keeps one inconsistent legacy row from
            # turning the whole dashboard into a 500 response.
            return min(1.0, max(0.0, round(int(value) / active_products, 4)))

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
    response = DashboardResponse(
        generated_at=now,
        data_scope="TENANT" if tenant_scope else "SELF",
        metrics=metrics,
        # Kept as an empty compatibility field for older clients.  Import
        # history is no longer loaded by the overview; source-file provenance
        # remains on the product/SKU records and import-job detail screens.
        recent_imports=[],
        data_health=data_health,
    )
    query_cache.store(
        cache_slot,
        response.model_dump(mode="json"),
        ttl_seconds=query_cache.configured_ttl(
            "QUERY_CACHE_DASHBOARD_TTL_SECONDS",
            30,
            maximum=300,
        ),
    )
    return response


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
        contact_name=row.contact_name,
        phone=row.phone,
        email=row.email,
        whatsapp=row.whatsapp,
        wechat=row.wechat,
        country_region=row.country_region,
        address=row.address,
        business_scope=row.business_scope,
        notes=row.notes,
        status=row.status,
        risk_level=row.risk_level,
        health=row.health,
        version=row.version,
        active_products=int(maps["products"].get(row.id, 0)),
        active_skus=max(
            int(maps["skus"].get(row.id, 0)),
            int(row.active_skus or 0),
        ),
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
    rows = repository.list_supplier_rows(session, tenant_id=tenant_id)
    maps = repository.supplier_aggregate_maps(
        session,
        tenant_id=tenant_id,
        now=now,
        supplier_ids={row.id for row in rows},
    )
    return [_supplier_summary(row, maps) for row in rows]


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
        session,
        tenant_id=tenant_id,
        now=datetime.now(UTC),
        supplier_ids={row.id},
    )
    return _supplier_summary(row, maps)


def get_supplier(session: Session, *, tenant_id: UUID, permissions: frozenset[str], supplier_id: str) -> SupplierProfileDetail:
    _require_any(permissions, "supplier.view", "supplier.manage")
    row = repository.get_supplier_row(session, tenant_id=tenant_id, supplier_id=supplier_id)
    if row is None:
        raise ApplicationError("SUPPLIER_NOT_FOUND", "Supplier was not found.", kind="not_found")
    now = datetime.now(UTC)
    maps = repository.supplier_aggregate_maps(
        session,
        tenant_id=tenant_id,
        now=now,
        supplier_ids={row.id},
    )
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


def list_supply_chain_partners(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    query: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> SupplyChainPageResponse:
    _require_any(permissions, "supplier.view", "supplier.manage")
    rows, total = repository.list_supply_chain_rows(
        session,
        tenant_id=tenant_id,
        query=query,
        status=status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    maps = repository.supplier_aggregate_maps(
        session,
        tenant_id=tenant_id,
        now=datetime.now(UTC),
        supplier_ids={row.id for row in rows},
    )
    return SupplyChainPageResponse(
        items=[_supplier_summary(row, maps) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


def create_supply_chain_partner(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: SupplyChainCreateRequest,
) -> SupplierProfileSummary:
    _require(permissions, "supplier.manage")
    if repository.supplier_name_exists(
        session,
        tenant_id=tenant_id,
        name=request.name,
    ):
        raise ApplicationError(
            "SUPPLY_CHAIN_NAME_CONFLICT",
            "已存在同名供应链，请确认后再保存。",
            kind="conflict",
        )
    row = SupplierRow(
        id=f"SUP-{uuid4().hex[:12].upper()}",
        tenant_id=tenant_id,
        supplier_code=f"SC-{uuid4().hex[:10].upper()}",
        name=request.name,
        category="供应链",
        category_summary="供应链资料",
        contact_name=request.contact_name,
        phone=request.phone,
        email=request.email,
        whatsapp=request.whatsapp,
        wechat=request.wechat,
        country_region=request.country_region,
        address=request.address,
        website=request.website,
        business_scope=request.business_scope,
        notes=request.notes,
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
            "SUPPLY_CHAIN_CONFLICT",
            "供应链资料与现有记录冲突，请确认后再保存。",
            kind="conflict",
        ) from exc
    session.refresh(row)
    maps = repository.supplier_aggregate_maps(
        session,
        tenant_id=tenant_id,
        now=datetime.now(UTC),
        supplier_ids={row.id},
    )
    return _supplier_summary(row, maps)


def update_supply_chain_partner(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    supplier_id: str,
    request: SupplyChainUpdateRequest,
) -> SupplierProfileSummary:
    _require(permissions, "supplier.manage")
    row = repository.get_supplier_row(
        session,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
    )
    if row is None:
        raise ApplicationError(
            "SUPPLY_CHAIN_NOT_FOUND",
            "没有找到这条供应链资料。",
            kind="not_found",
        )
    if row.version != request.expected_version:
        raise ApplicationError(
            "SUPPLY_CHAIN_VERSION_CONFLICT",
            "这条供应链资料已被更新，请刷新后重试。",
            kind="conflict",
        )
    changed_fields = request.model_fields_set - {"expected_version"}
    if not changed_fields:
        raise ApplicationError(
            "SUPPLY_CHAIN_NO_CHANGES",
            "没有需要保存的修改。",
        )
    if "status" in changed_fields and request.status is None:
        raise ApplicationError(
            "SUPPLY_CHAIN_STATUS_REQUIRED",
            "请选择合作状态。",
        )
    if "name" in changed_fields:
        if not request.name:
            raise ApplicationError(
                "SUPPLY_CHAIN_NAME_REQUIRED",
                "请填写工厂或合作方名称。",
            )
        if repository.supplier_name_exists(
            session,
            tenant_id=tenant_id,
            name=request.name,
            exclude_supplier_id=supplier_id,
        ):
            raise ApplicationError(
                "SUPPLY_CHAIN_NAME_CONFLICT",
                "已存在同名供应链，请确认后再保存。",
                kind="conflict",
            )
    values = request.model_dump(
        exclude={"expected_version"},
        exclude_unset=True,
    )
    for field, value in values.items():
        setattr(row, field, value)
    row.version += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPLY_CHAIN_CONFLICT",
            "供应链资料与现有记录冲突，请确认后再保存。",
            kind="conflict",
        ) from exc
    session.refresh(row)
    maps = repository.supplier_aggregate_maps(
        session,
        tenant_id=tenant_id,
        now=datetime.now(UTC),
        supplier_ids={row.id},
    )
    return _supplier_summary(row, maps)


def delete_supply_chain_partner(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    supplier_id: str,
) -> None:
    _require(permissions, "supplier.manage")
    row = repository.get_supplier_row(
        session,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
    )
    if row is None:
        raise ApplicationError(
            "SUPPLY_CHAIN_NOT_FOUND",
            "没有找到这条供应链资料。",
            kind="not_found",
        )
    maps = repository.supplier_aggregate_maps(
        session,
        tenant_id=tenant_id,
        now=datetime.now(UTC),
        supplier_ids={row.id},
    )
    linked_products = int(maps["products"].get(row.id, 0))
    linked_skus = int(maps["skus"].get(row.id, 0))
    if linked_products or linked_skus or row.active_skus:
        raise ApplicationError(
            "SUPPLY_CHAIN_IN_USE",
            "这条供应链已关联商品，不能删除；可以将它停用。",
            kind="conflict",
        )
    row.status = "ARCHIVED"
    row.version += 1
    mark_deleted(row)
    session.commit()
