from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..product_center_models import (
    AttributeDefinitionRow,
    ProductAuditEventRow,
    SKU_TEMPLATE_SOURCE_OPTION_KEY,
    SkuRow,
    SupplierPriceRow,
)
from ..product_center_schemas import (
    AttributeDefinitionCreateRequest,
    AttributeDefinitionResponse,
    CategoryCreateRequest,
    CategoryReorderRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    ProductAttributeResponse,
    ProductAuditEventResponse,
    ProductCard,
    ProductCategorySummary,
    ProductDetail,
    ProductOfferSummary,
    PublicCatalogOfferResponse,
    PublicCatalogOfferUpsertRequest,
    ProductReviewQueueItem,
    ReviewQueueField,
    SkuBatchCreateRequest,
    SkuBatchDeleteRequest,
    SkuBatchUpdateStatusRequest,
    SkuBatchOperationResponse,
    SkuListItem,
    SkuListPage,
    SkuResponse,
    SkuSupplierSummary,
    SkuUpdateRequest,
    SupplierPriceCreateRequest,
    SupplierPriceResponse,
)
from ..product_supplier_models import ProductCategoryRow, ProductRow
from ..public_catalog_models import PublicCatalogOfferRow
from ..repositories import product_center_repository as repository


FIELD_LABELS = {
    "name": "产品名称",
    "product_code": "产品编码",
    "sku": "SKU / 型号",
    "material": "材质",
    "color": "颜色",
    "size": "尺寸",
    "moq": "MOQ",
    "packing": "包装",
    "description": "产品描述",
}

SKU_STATUSES = frozenset({"DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"})


def _require(permissions: frozenset[str], permission: str) -> None:
    if permission not in permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            f"Permission required: {permission}",
            kind="forbidden",
        )


def _commit(session: Session, *, conflict_code: str, conflict_message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(conflict_code, conflict_message, kind="conflict") from exc


def _decimal(value: Decimal | None) -> Decimal | None:
    return value


def _category_display_name(category: ProductCategoryRow) -> str:
    path = (category.path or "").strip()
    if not path or path.casefold() == category.code.casefold():
        return category.name
    return path


def _price_validity(price: SupplierPriceRow | None, *, now: datetime | None = None) -> str:
    if price is None or price.status != "CONFIRMED":
        return "UNKNOWN"
    now = now or datetime.now(UTC)
    valid_to = price.valid_to
    if valid_to is None:
        return "VALID"
    if valid_to.tzinfo is None:
        valid_to = valid_to.replace(tzinfo=UTC)
    if valid_to < now:
        return "EXPIRED"
    if valid_to <= now + timedelta(days=30):
        return "EXPIRING"
    return "VALID"


def _sku_response(row: SkuRow) -> SkuResponse:
    return SkuResponse(
        id=row.id,
        product_id=row.product_id,
        sku_code=row.sku_code,
        name=row.name,
        option_values=row.option_values,
        barcode=row.barcode,
        default_moq=row.default_moq,
        moq_unit=row.moq_unit,
        weight=row.weight,
        weight_unit=row.weight_unit,
        status=row.status,
        version=row.version,
        updated_at=row.updated_at,
    )


def _public_offer_response(row: PublicCatalogOfferRow) -> PublicCatalogOfferResponse:
    return PublicCatalogOfferResponse(
        id=row.id,
        sku_id=row.sku_id,
        unit_price=row.unit_price,
        currency=row.currency,
        tags=row.tags,
        display_tag=row.display_tag,
        tag_color=row.tag_color,
        publication_status=row.publication_status,
        published_at=row.published_at,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _attribute_value(row: Any) -> Any:
    for value in (row.value_text, row.value_number, row.value_boolean, row.value_json):
        if value is not None:
            return value
    return None


def _offers(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
    can_read_cost: bool,
) -> list[ProductOfferSummary]:
    sources = repository.list_sources(session, tenant_id=tenant_id, product_id=product_id)
    prices = repository.list_prices_for_product(
        session, tenant_id=tenant_id, product_id=product_id
    )
    latest_price_by_source: dict[UUID, SupplierPriceRow] = {}
    for price, source, _supplier in prices:
        if price.status == "CONFIRMED":
            latest_price_by_source.setdefault(source.id, price)
    return [
        ProductOfferSummary(
            supplier_product_id=source.id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            supplier_sku=source.supplier_sku,
            sku_id=source.sku_id,
            moq=source.moq,
            moq_unit=source.moq_unit,
            lead_time_days=source.lead_time_days,
            unit_price=(
                latest_price_by_source[source.id].unit_price
                if can_read_cost and source.id in latest_price_by_source
                else None
            ),
            currency=(
                latest_price_by_source[source.id].currency
                if can_read_cost and source.id in latest_price_by_source
                else None
            ),
            price_validity=_price_validity(latest_price_by_source.get(source.id)),
            valid_to=(
                latest_price_by_source[source.id].valid_to
                if source.id in latest_price_by_source
                else None
            ),
        )
        for source, supplier in sources
    ]


def _card(
    session: Session,
    *,
    tenant_id: UUID,
    product: Any,
    permissions: frozenset[str],
) -> ProductCard:
    category = repository.get_category(
        session, tenant_id=tenant_id, category_id=product.category_id
    )
    attributes = repository.list_attributes(
        session, tenant_id=tenant_id, product_id=product.id
    )
    material = next(
        (
            str(_attribute_value(attribute))
            for attribute in attributes
            if attribute.attribute_key == "material" and attribute.review_status == "CONFIRMED"
        ),
        None,
    )
    skus = repository.list_skus(session, tenant_id=tenant_id, product_id=product.id)
    images = repository.list_images(session, tenant_id=tenant_id, product_id=product.id)
    image_status = (
        "APPROVED"
        if any(image.approval_status == "APPROVED" for image in images)
        else "SOURCE" if images else "NONE"
    )
    offers = _offers(
        session,
        tenant_id=tenant_id,
        product_id=product.id,
        can_read_cost="product.cost.read" in permissions,
    )
    current_offer = next(
        (offer for offer in offers if offer.price_validity in {"VALID", "EXPIRING"}),
        offers[0] if offers else None,
    )
    model = skus[0].sku_code if skus else (current_offer.supplier_sku if current_offer else "")
    capabilities = ["read"]
    if "product.edit" in permissions:
        capabilities.extend(["edit", "manage_skus"])
    if "product.cost.read" in permissions:
        capabilities.append("view_cost")
    return ProductCard(
        id=product.id,
        product_code=product.product_code,
        name=product.name,
        status=product.status,
        category=(
            ProductCategorySummary(
                id=category.id,
                code=category.code,
                name=_category_display_name(category),
            )
            if category
            else None
        ),
        material=material,
        sku_count=len(skus),
        supplier_count=len(offers),
        primary_image_url=None,
        image_status=image_status,
        current_offer=current_offer,
        current_version=product.current_version,
        updated_at=product.updated_at,
        capabilities=capabilities,
        model=model,
        supplier=current_offer.supplier_name if current_offer else "Unassigned",
        price=current_offer.unit_price if current_offer else None,
        currency=current_offer.currency if current_offer else None,
        moq=current_offer.moq if current_offer else None,
        tags=[value for value in [category.name if category else None, material] if value],
    )


def list_products(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    query: str,
    category_id: UUID | None,
    supplier_id: str | None,
    statuses: list[str],
    approved_images_only: bool,
    limit: int,
) -> list[ProductCard]:
    _require(permissions, "product.view")
    rows = repository.list_product_rows(
        session,
        tenant_id=tenant_id,
        query=query,
        category_id=category_id,
        supplier_id=supplier_id,
        statuses=statuses,
        approved_images_only=approved_images_only,
        limit=limit,
    )
    return [
        _card(session, tenant_id=tenant_id, product=row, permissions=permissions)
        for row in rows
    ]


def list_skus(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    query: str,
    category_id: UUID | None,
    statuses: list[str],
    page: int,
    page_size: int,
    include_supplier_summary: bool = True,
) -> SkuListPage:
    _require(permissions, "product.view")
    normalized_statuses = sorted(
        {status.strip().upper() for status in statuses if status.strip()}
    )
    invalid_statuses = set(normalized_statuses) - SKU_STATUSES
    if invalid_statuses:
        raise ApplicationError(
            "SKU_STATUS_INVALID",
            f"Unsupported SKU status: {', '.join(sorted(invalid_statuses))}",
        )

    rows, total = repository.list_sku_page_rows(
        session,
        tenant_id=tenant_id,
        query=query,
        category_id=category_id,
        statuses=normalized_statuses,
        page=page,
        page_size=page_size,
    )
    sku_ids = {row.sku.id for row in rows}
    product_ids = {row.product.id for row in rows}
    direct_suppliers = {
        supplier.id: supplier
        for supplier in repository.list_suppliers_by_ids(
            session,
            tenant_id=tenant_id,
            supplier_ids={
                row.sku.supplier_id
                for row in rows
                if row.sku.supplier_id is not None
            },
        )
    }

    suppliers_by_sku: dict[UUID, list[tuple[Any, Any]]] = {}
    suppliers_by_product: dict[UUID, list[tuple[Any, Any]]] = {}
    if include_supplier_summary:
        for source, supplier in repository.list_supplier_rows_for_sku_page(
            session,
            tenant_id=tenant_id,
            sku_ids=sku_ids,
            product_ids=product_ids,
        ):
            target = (
                suppliers_by_sku.setdefault(source.sku_id, [])
                if source.sku_id is not None
                else suppliers_by_product.setdefault(source.product_id, [])
            )
            target.append((source, supplier))

    image_statuses_by_product: dict[UUID, set[str]] = {}
    for product_id, approval_status in repository.list_image_statuses_for_products(
        session,
        tenant_id=tenant_id,
        product_ids=product_ids,
    ):
        image_statuses_by_product.setdefault(product_id, set()).add(approval_status)

    items: list[SkuListItem] = []
    for row in rows:
        supplier_rows = [
            *suppliers_by_sku.get(row.sku.id, []),
            *suppliers_by_product.get(row.product.id, []),
        ]
        unique_suppliers: list[Any] = []
        seen_supplier_ids: set[str] = set()
        direct_supplier = direct_suppliers.get(row.sku.supplier_id)
        if direct_supplier is not None:
            seen_supplier_ids.add(direct_supplier.id)
            unique_suppliers.append(direct_supplier)
        for _source, supplier in supplier_rows:
            if supplier.id in seen_supplier_ids:
                continue
            seen_supplier_ids.add(supplier.id)
            unique_suppliers.append(supplier)

        image_states = image_statuses_by_product.get(row.product.id, set())
        image_status = (
            "APPROVED"
            if "APPROVED" in image_states
            else "SOURCE" if image_states else "NONE"
        )
        offer = row.public_offer
        items.append(
            SkuListItem(
                id=row.sku.id,
                sku_code=row.sku.sku_code,
                name=row.sku.name or row.product.name,
                product_id=row.product.id,
                product_code=row.product.product_code,
                product_name=row.product.name,
                category=(
                    ProductCategorySummary(
                        id=row.category.id,
                        code=row.category.code,
                        name=_category_display_name(row.category),
                    )
                    if row.category
                    else None
                ),
                tags=list(offer.tags) if offer else [],
                supplier_summary=SkuSupplierSummary(
                    count=len(unique_suppliers),
                    primary_supplier_id=(
                        unique_suppliers[0].id if unique_suppliers else None
                    ),
                    primary_supplier_name=(
                        unique_suppliers[0].name if unique_suppliers else None
                    ),
                    names=[supplier.name for supplier in unique_suppliers[:3]],
                ),
                default_moq=row.sku.default_moq,
                moq_unit=row.sku.moq_unit,
                public_price=offer.unit_price if offer else None,
                public_currency=offer.currency if offer else None,
                public_offer_status=offer.publication_status if offer else None,
                status=row.sku.status,
                version=row.sku.version,
                updated_at=row.sku.updated_at,
                image_status=image_status,
            )
        )

    return SkuListPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=(total + page_size - 1) // page_size,
    )


def get_product(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
) -> ProductDetail:
    _require(permissions, "product.view")
    product = repository.get_product_row(session, tenant_id=tenant_id, product_id=product_id)
    if product is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    card = _card(session, tenant_id=tenant_id, product=product, permissions=permissions)
    attributes = repository.list_attributes(session, tenant_id=tenant_id, product_id=product.id)
    skus = repository.list_skus(session, tenant_id=tenant_id, product_id=product.id)
    audit = repository.list_audit_events(session, tenant_id=tenant_id, product_id=product.id)
    return ProductDetail(
        **card.model_dump(),
        description=product.description,
        default_unit=product.default_unit,
        attributes=[
            ProductAttributeResponse(
                id=row.id,
                definition_id=row.attribute_definition_id,
                key=row.attribute_key,
                value=_attribute_value(row),
                unit_code=row.unit_code,
                review_status=row.review_status,
            )
            for row in attributes
        ],
        skus=[_sku_response(row) for row in skus],
        sources=_offers(
            session,
            tenant_id=tenant_id,
            product_id=product.id,
            can_read_cost="product.cost.read" in permissions,
        ),
        activity=[
            ProductAuditEventResponse(
                id=row.id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                action=row.action,
                before=row.before,
                after=row.after,
                actor_membership_id=row.actor_membership_id,
                occurred_at=row.occurred_at,
            )
            for row in audit
        ],
    )


def create_skus(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
    request: SkuBatchCreateRequest,
) -> list[SkuResponse]:
    _require(permissions, "product.edit")
    product = repository.get_product_row(session, tenant_id=tenant_id, product_id=product_id)
    if product is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    definitions = repository.list_attribute_definitions(
        session, tenant_id=tenant_id, category_id=product.category_id
    )
    variant_keys = {row.attribute_key for row in definitions if row.is_variant and row.status == "ACTIVE"}
    for item in request.items:
        if repository.sku_code_exists(session, tenant_id=tenant_id, sku_code=item.sku_code):
            raise ApplicationError(
                "SKU_CODE_CONFLICT",
                f"SKU code already exists: {item.sku_code}",
                kind="conflict",
            )
        invalid_keys = set(item.option_values) - variant_keys
        if invalid_keys:
            raise ApplicationError(
                "SKU_VARIANT_ATTRIBUTE_INVALID",
                f"Variant attributes are not allowed by the category template: {', '.join(sorted(invalid_keys))}",
            )
    rows: list[SkuRow] = []
    now = utcnow()
    for item in request.items:
        row = SkuRow(
            tenant_id=tenant_id,
            product_id=product_id,
            sku_code=item.sku_code,
            name=item.name,
            option_values=item.option_values,
            barcode=item.barcode,
            default_moq=item.default_moq,
            moq_unit=item.moq_unit,
            weight=item.weight,
            weight_unit=item.weight_unit,
            status=item.status,
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        session.add(row)
        session.flush()
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product_id,
                entity_type="SKU",
                entity_id=str(row.id),
                action="sku.created",
                before={},
                after=item.model_dump(mode="json"),
                actor_membership_id=membership_id,
                occurred_at=now,
            )
        )
        rows.append(row)
    product.search_document_version = 0
    _commit(session, conflict_code="SKU_CODE_CONFLICT", conflict_message="SKU code already exists.")
    return [_sku_response(row) for row in rows]


def update_sku(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_id: UUID,
    request: SkuUpdateRequest,
) -> SkuResponse:
    _require(permissions, "product.edit")
    row = repository.get_sku(session, tenant_id=tenant_id, sku_id=sku_id)
    if row is None:
        raise ApplicationError("SKU_NOT_FOUND", "SKU was not found.", kind="not_found")
    if row.version != request.expected_version:
        raise ApplicationError(
            "SKU_VERSION_CONFLICT",
            "SKU has been changed by another user.",
            kind="conflict",
        )
    before = _sku_response(row).model_dump(mode="json")
    for field, value in request.model_dump(exclude={"expected_version"}, exclude_unset=True).items():
        if field == "option_values" and value is not None:
            # Template ownership is server-managed metadata. Users may edit
            # visible variant values, but cannot remove or forge the marker
            # that makes later authoritative snapshots safe.
            editable_values = dict(value)
            editable_values.pop(SKU_TEMPLATE_SOURCE_OPTION_KEY, None)
            source_marker = row.option_values.get(SKU_TEMPLATE_SOURCE_OPTION_KEY)
            if source_marker is not None:
                editable_values[SKU_TEMPLATE_SOURCE_OPTION_KEY] = source_marker
                if "备注" in row.option_values:
                    editable_values["备注"] = row.option_values["备注"]
                else:
                    editable_values.pop("备注", None)
            value = editable_values
        setattr(row, field, value)
    row.version += 1
    row.updated_by_user_id = user_id
    product = repository.get_product_row(
        session,
        tenant_id=tenant_id,
        product_id=row.product_id,
    )
    if product is not None:
        product.search_document_version = 0
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=row.product_id,
            entity_type="SKU",
            entity_id=str(row.id),
            action="sku.updated",
            before=before,
            after={**request.model_dump(mode="json", exclude_unset=True), "version": row.version},
            actor_membership_id=membership_id,
        )
    )
    session.commit()
    session.refresh(row)
    return _sku_response(row)


def list_public_offers(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
) -> list[PublicCatalogOfferResponse]:
    _require(permissions, "catalog.view")
    if repository.get_product_row(session, tenant_id=tenant_id, product_id=product_id) is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    return [
        _public_offer_response(row)
        for row in repository.list_public_offers_for_product(
            session, tenant_id=tenant_id, product_id=product_id
        )
    ]


def upsert_public_offer(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_id: UUID,
    request: PublicCatalogOfferUpsertRequest,
) -> PublicCatalogOfferResponse:
    _require(permissions, "catalog.publish")
    sku = repository.get_sku(session, tenant_id=tenant_id, sku_id=sku_id)
    if sku is None:
        raise ApplicationError("SKU_NOT_FOUND", "SKU was not found.", kind="not_found")
    product = repository.get_product_row(
        session, tenant_id=tenant_id, product_id=sku.product_id
    )
    if product is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    if request.publication_status == "PUBLISHED":
        if product.status != "ACTIVE":
            raise ApplicationError(
                "PUBLIC_PRODUCT_NOT_ACTIVE",
                "Activate the Product before publishing a public offer.",
                kind="conflict",
            )
        if sku.status != "ACTIVE":
            raise ApplicationError(
                "PUBLIC_SKU_NOT_ACTIVE",
                "Activate the SKU before publishing a public offer.",
                kind="conflict",
            )

    row = repository.get_public_offer(session, tenant_id=tenant_id, sku_id=sku_id)
    before = _public_offer_response(row).model_dump(mode="json") if row is not None else {}
    now = utcnow()
    if row is None:
        row = PublicCatalogOfferRow(tenant_id=tenant_id, sku_id=sku_id)
        session.add(row)
    for field, value in request.model_dump().items():
        setattr(row, field, value)
    if request.publication_status == "PUBLISHED":
        row.published_at = now
    elif request.publication_status == "DRAFT":
        row.published_at = None
    product.search_document_version = 0
    session.flush()
    after = _public_offer_response(row).model_dump(mode="json")
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=sku.product_id,
            entity_type="SKU",
            entity_id=str(sku.id),
            action=f"public_offer.{request.publication_status.casefold()}",
            before=before,
            after=after,
            actor_membership_id=membership_id,
            occurred_at=now,
        )
    )
    _commit(
        session,
        conflict_code="PUBLIC_OFFER_CONFLICT",
        conflict_message="Public offer could not be saved because it changed concurrently.",
    )
    session.refresh(row)
    return _public_offer_response(row)


def list_categories(
    session: Session, *, tenant_id: UUID, permissions: frozenset[str]
) -> list[CategoryResponse]:
    _require(permissions, "product.view")
    return [
        CategoryResponse(
            id=row.id,
            parent_id=row.parent_id,
            code=row.code,
            name=row.name,
            sort_order=row.sort_order,
            display_color=row.display_color,
            path=row.path,
            status=row.status,
            version=row.version,
        )
        for row in repository.list_categories(session, tenant_id=tenant_id)
    ]


def _category_response(row: ProductCategoryRow) -> CategoryResponse:
    return CategoryResponse(
        id=row.id,
        parent_id=row.parent_id,
        code=row.code,
        name=row.name,
        sort_order=row.sort_order,
        display_color=row.display_color,
        path=row.path,
        status=row.status,
        version=row.version,
    )


def create_category(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: CategoryCreateRequest,
) -> CategoryResponse:
    _require(permissions, "product.edit")
    parent = repository.get_category(
        session, tenant_id=tenant_id, category_id=request.parent_id
    )
    if request.parent_id is not None and parent is None:
        raise ApplicationError("CATEGORY_PARENT_NOT_FOUND", "Parent category was not found.")
    if parent is not None and parent.parent_id is not None:
        raise ApplicationError(
            "CATEGORY_DEPTH_EXCEEDED",
            "分类最多两级，不能在二级分类下继续新增。",
            kind="conflict",
        )
    if repository.find_sibling_category(
        session,
        tenant_id=tenant_id,
        parent_id=request.parent_id,
        name=request.name,
    ):
        raise ApplicationError(
            "CATEGORY_NAME_CONFLICT",
            "同一级下已经存在同名分类。",
            kind="conflict",
        )
    path = f"{parent.name}/{request.name}" if parent else request.name
    row = ProductCategoryRow(
        tenant_id=tenant_id,
        parent_id=request.parent_id,
        code=request.code,
        name=request.name,
        path=path,
        sort_order=request.sort_order,
        display_color=request.display_color if parent is None else None,
        status="ACTIVE",
    )
    session.add(row)
    session.flush()
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="CATEGORY",
            entity_id=str(row.id),
            action="category.created",
            before={},
            after=request.model_dump(mode="json"),
            actor_membership_id=membership_id,
        )
    )
    _commit(
        session,
        conflict_code="CATEGORY_CODE_CONFLICT",
        conflict_message="Category code already exists.",
    )
    return _category_response(row)


def reorder_categories(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: CategoryReorderRequest,
) -> list[CategoryResponse]:
    _require(permissions, "product.edit")
    requested_ids = [item.id for item in request.items]
    rows = repository.list_categories_by_ids(
        session, tenant_id=tenant_id, category_ids=requested_ids
    )
    if len(rows) != len(requested_ids):
        raise ApplicationError(
            "CATEGORY_NOT_FOUND",
            "部分分类不存在，请刷新后重试。",
            kind="not_found",
        )
    rows_by_id = {row.id: row for row in rows}
    parent_ids = {row.parent_id for row in rows}
    if len(parent_ids) != 1:
        raise ApplicationError(
            "CATEGORY_REORDER_LEVEL_MISMATCH",
            "只能调整同一层级、同一上级下的分类顺序。",
            kind="conflict",
        )
    parent_id = next(iter(parent_ids))
    siblings = repository.list_sibling_categories(
        session, tenant_id=tenant_id, parent_id=parent_id
    )
    if {row.id for row in siblings} != set(requested_ids):
        raise ApplicationError(
            "CATEGORY_REORDER_STALE",
            "分类列表已发生变化，请刷新后重新排序。",
            kind="conflict",
        )
    for item in request.items:
        if rows_by_id[item.id].version != item.expected_version:
            raise ApplicationError(
                "CATEGORY_VERSION_CONFLICT",
                "分类已被其他人修改，请刷新后重试。",
                kind="conflict",
            )

    for position, item in enumerate(request.items):
        row = rows_by_id[item.id]
        if row.sort_order == position:
            continue
        before = _category_response(row).model_dump(mode="json")
        row.sort_order = position
        row.version += 1
        after = _category_response(row).model_dump(mode="json")
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=None,
                entity_type="CATEGORY",
                entity_id=str(row.id),
                action="category.reordered",
                before=before,
                after=after,
                actor_membership_id=membership_id,
            )
        )
    session.flush()
    _commit(
        session,
        conflict_code="CATEGORY_REORDER_CONFLICT",
        conflict_message="分类顺序保存失败，请刷新后重试。",
    )
    return [_category_response(rows_by_id[item.id]) for item in request.items]


def update_category(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    category_id: UUID,
    request: CategoryUpdateRequest,
) -> CategoryResponse:
    _require(permissions, "product.edit")
    row = repository.get_category(
        session, tenant_id=tenant_id, category_id=category_id
    )
    if row is None:
        raise ApplicationError(
            "CATEGORY_NOT_FOUND", "分类不存在。", kind="not_found"
        )
    if row.version != request.expected_version:
        raise ApplicationError(
            "CATEGORY_VERSION_CONFLICT",
            "分类已被其他人修改，请刷新后重试。",
            kind="conflict",
        )
    if request.parent_id == row.id:
        raise ApplicationError(
            "CATEGORY_PARENT_INVALID", "分类不能作为自己的上级。", kind="conflict"
        )
    parent = repository.get_category(
        session, tenant_id=tenant_id, category_id=request.parent_id
    )
    if request.parent_id is not None and parent is None:
        raise ApplicationError(
            "CATEGORY_PARENT_NOT_FOUND", "上级分类不存在。", kind="not_found"
        )
    if parent is not None and parent.parent_id is not None:
        raise ApplicationError(
            "CATEGORY_DEPTH_EXCEEDED",
            "分类最多两级，只能选择一级分类作为上级。",
            kind="conflict",
        )
    children = repository.list_child_categories(
        session, tenant_id=tenant_id, parent_id=row.id
    )
    if parent is not None and children:
        raise ApplicationError(
            "CATEGORY_DEPTH_EXCEEDED",
            "该一级分类仍有二级分类，不能移动到另一个分类下面。",
            kind="conflict",
        )
    if repository.find_sibling_category(
        session,
        tenant_id=tenant_id,
        parent_id=request.parent_id,
        name=request.name,
        exclude_id=row.id,
    ):
        raise ApplicationError(
            "CATEGORY_NAME_CONFLICT",
            "同一级下已经存在同名分类。",
            kind="conflict",
        )

    before = _category_response(row).model_dump(mode="json")
    row.parent_id = request.parent_id
    row.name = request.name
    row.path = f"{parent.name}/{request.name}" if parent else request.name
    row.sort_order = request.sort_order
    row.status = request.status
    if parent is not None:
        row.display_color = None
    elif "display_color" in request.model_fields_set:
        row.display_color = request.display_color
    row.version += 1
    if children:
        for child in children:
            child.path = f"{request.name}/{child.name}"
            child.version += 1
    affected_category_ids = [row.id, *(child.id for child in children)]
    session.execute(
        update(ProductRow)
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.category_id.in_(affected_category_ids),
            ProductRow.status == "ACTIVE",
        )
        .values(search_document_version=0)
    )
    session.flush()
    after = _category_response(row).model_dump(mode="json")
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="CATEGORY",
            entity_id=str(row.id),
            action="category.updated",
            before=before,
            after=after,
            actor_membership_id=membership_id,
        )
    )
    _commit(
        session,
        conflict_code="CATEGORY_UPDATE_CONFLICT",
        conflict_message="分类保存失败，请刷新后重试。",
    )
    return _category_response(row)


def list_attribute_definitions(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    category_id: UUID | None,
) -> list[AttributeDefinitionResponse]:
    _require(permissions, "product.view")
    return [
        AttributeDefinitionResponse(
            id=row.id,
            category_id=row.category_id,
            attribute_key=row.attribute_key,
            display_name=row.display_name,
            data_type=row.data_type,
            unit_code=row.unit_code,
            enum_values=row.enum_values,
            is_required=row.is_required,
            is_variant=row.is_variant,
            is_filterable=row.is_filterable,
            is_matchable=row.is_matchable,
            status=row.status,
            version=row.version,
        )
        for row in repository.list_attribute_definitions(
            session, tenant_id=tenant_id, category_id=category_id
        )
    ]


def create_attribute_definition(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: AttributeDefinitionCreateRequest,
) -> AttributeDefinitionResponse:
    _require(permissions, "product.edit")
    if request.category_id and repository.get_category(
        session, tenant_id=tenant_id, category_id=request.category_id
    ) is None:
        raise ApplicationError("CATEGORY_NOT_FOUND", "Category was not found.", kind="not_found")
    row = AttributeDefinitionRow(
        tenant_id=tenant_id,
        **request.model_dump(),
        status="ACTIVE",
        version=1,
    )
    session.add(row)
    session.flush()
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="ATTRIBUTE_DEFINITION",
            entity_id=str(row.id),
            action="attribute_definition.created",
            before={},
            after=request.model_dump(mode="json"),
            actor_membership_id=membership_id,
        )
    )
    _commit(
        session,
        conflict_code="ATTRIBUTE_DEFINITION_CONFLICT",
        conflict_message="Attribute key already exists for this category.",
    )
    return AttributeDefinitionResponse(
        id=row.id,
        category_id=row.category_id,
        attribute_key=row.attribute_key,
        display_name=row.display_name,
        data_type=row.data_type,
        unit_code=row.unit_code,
        enum_values=row.enum_values,
        is_required=row.is_required,
        is_variant=row.is_variant,
        is_filterable=row.is_filterable,
        is_matchable=row.is_matchable,
        status=row.status,
        version=row.version,
    )


def list_prices(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
) -> list[SupplierPriceResponse]:
    _require(permissions, "product.cost.read")
    if repository.get_product_row(session, tenant_id=tenant_id, product_id=product_id) is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    return [
        SupplierPriceResponse(
            id=price.id,
            product_id=source.product_id,
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            supplier_product_id=source.id,
            sku_id=price.sku_id,
            min_quantity=price.min_quantity,
            max_quantity=price.max_quantity,
            unit_price=price.unit_price,
            currency=price.currency,
            unit_code=price.unit_code,
            incoterm=price.incoterm,
            tax_status=price.tax_status,
            valid_from=price.valid_from,
            valid_to=price.valid_to,
            source_evidence_id=price.source_evidence_id,
            supersedes_price_id=price.supersedes_price_id,
            status=price.status,
            price_validity=_price_validity(price),
            confirmed_by_membership_id=price.confirmed_by_membership_id,
            confirmed_at=price.confirmed_at,
            created_at=price.created_at,
        )
        for price, source, supplier in repository.list_prices_for_product(
            session, tenant_id=tenant_id, product_id=product_id
        )
    ]


def create_price(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: SupplierPriceCreateRequest,
) -> SupplierPriceResponse:
    _require(permissions, "product.cost.write")
    source = repository.get_supplier_product(
        session, tenant_id=tenant_id, supplier_product_id=request.supplier_product_id
    )
    if source is None:
        raise ApplicationError("SUPPLIER_PRODUCT_NOT_FOUND", "Supplier product was not found.")
    if request.sku_id:
        sku = repository.get_sku(session, tenant_id=tenant_id, sku_id=request.sku_id)
        if sku is None or sku.product_id != source.product_id:
            raise ApplicationError("PRICE_SKU_MISMATCH", "SKU does not belong to this Product.")
    if request.supersedes_price_id:
        prior = repository.get_price(
            session, tenant_id=tenant_id, price_id=request.supersedes_price_id
        )
        if prior is None or prior.supplier_product_id != source.id:
            raise ApplicationError(
                "SUPERSEDED_PRICE_MISMATCH",
                "Superseded price must belong to the same supplier source.",
            )
    now = utcnow()
    row = SupplierPriceRow(
        tenant_id=tenant_id,
        **request.model_dump(),
        status="CONFIRMED",
        confirmed_by_membership_id=membership_id,
        confirmed_at=now,
    )
    session.add(row)
    session.flush()
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=source.product_id,
            entity_type="PRICE",
            entity_id=str(row.id),
            action="price.confirmed",
            before={},
            after=request.model_dump(mode="json"),
            actor_membership_id=membership_id,
            occurred_at=now,
        )
    )
    session.commit()
    created = next(
        item for item in list_prices(
        session,
        tenant_id=tenant_id,
        permissions=permissions | frozenset({"product.cost.read"}),
        product_id=source.product_id,
        ) if item.id == row.id
    )
    return created


def list_review_queue(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    limit: int,
) -> list[ProductReviewQueueItem]:
    _require(permissions, "product.review")
    pairs = repository.list_review_candidates(session, tenant_id=tenant_id, limit=limit * 12)
    task_ids = {candidate.ai_task_id for candidate, _evidence in pairs}
    decisions = repository.review_decisions_for_tasks(
        session, tenant_id=tenant_id, task_ids=task_ids
    )
    latest: dict[tuple[UUID, str], Any] = {}
    for decision in decisions:
        latest.setdefault((decision.ai_task_id, decision.candidate_group_key), decision)
    groups: dict[tuple[UUID, str], list[tuple[Any, Any]]] = {}
    for candidate, evidence in pairs:
        groups.setdefault((candidate.ai_task_id, candidate.candidate_group_key), []).append(
            (candidate, evidence)
        )
    result: list[ProductReviewQueueItem] = []
    for (task_id, group_key), rows in list(groups.items())[:limit]:
        decision = latest.get((task_id, group_key))
        status = (
            "approved"
            if decision and decision.action == "APPROVE"
            else "rejected" if decision and decision.action == "REJECT" else "pending"
        )
        by_key = {candidate.field_key: candidate for candidate, _evidence in rows}
        evidence = rows[0][1]
        location_value = evidence.location or {}
        location = ", ".join(f"{key}={value}" for key, value in location_value.items())
        fields: list[ReviewQueueField] = []
        for candidate, candidate_evidence in rows:
            normalized: Any = candidate.normalized_value
            if isinstance(normalized, dict):
                normalized = normalized.get("value", normalized.get("text", candidate.raw_value))
            fields.append(
                ReviewQueueField(
                    key=candidate.field_key,
                    label=FIELD_LABELS.get(candidate.field_key, candidate.field_key.replace("_", " ").title()),
                    source=str(candidate_evidence.location),
                    normalized=str(normalized if normalized is not None else candidate.raw_value),
                    confidence=candidate.confidence,
                )
            )
        result.append(
            ProductReviewQueueItem(
                id=f"{task_id}:{group_key}",
                task_id=task_id,
                candidate_group_key=group_key,
                status=status,
                name=by_key.get("name").raw_value if by_key.get("name") else "Name requires review",
                model=(
                    by_key.get("sku").raw_value
                    if by_key.get("sku")
                    else by_key.get("product_code").raw_value if by_key.get("product_code") else ""
                ),
                supplier=repository.supplier_name_for_source(
                    session, tenant_id=tenant_id, source_file_id=evidence.source_file_id
                ),
                source=evidence.source_file_id or "Source evidence",
                location=location or "Evidence location available",
                fields=fields,
                applied_product_id=decision.product_id if decision else None,
                applied_product_version=decision.applied_product_version if decision else None,
            )
        )
    return result


def batch_delete_skus(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_ids: list[UUID],
) -> dict[str, Any]:
    """批量删除 SKU"""
    _require(permissions, "product_center.write")

    success_count = 0
    failed_count = 0
    failed_items: list[dict[str, Any]] = []

    for sku_id in sku_ids:
        try:
            sku = session.query(SkuRow).filter(
                SkuRow.tenant_id == tenant_id,
                SkuRow.id == sku_id,
            ).first()

            if not sku:
                failed_count += 1
                failed_items.append({
                    "sku_id": str(sku_id),
                    "reason": "SKU not found"
                })
                continue

            session.delete(sku)
            success_count += 1
        except Exception as exc:
            failed_count += 1
            failed_items.append({
                "sku_id": str(sku_id),
                "reason": str(exc)
            })

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "BATCH_DELETE_FAILED",
            "批量删除失败，可能存在关联数据",
            kind="conflict"
        ) from exc

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "total_count": len(sku_ids),
        "failed_items": failed_items,
    }


def batch_update_sku_status(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_ids: list[UUID],
    status: str,
) -> dict[str, Any]:
    """批量更新 SKU 状态"""
    _require(permissions, "product_center.write")

    if status not in SKU_STATUSES:
        raise ApplicationError(
            "INVALID_STATUS",
            f"Invalid status: {status}",
            kind="validation_failed"
        )

    success_count = 0
    failed_count = 0
    failed_items: list[dict[str, Any]] = []
    now = utcnow()

    for sku_id in sku_ids:
        try:
            sku = session.query(SkuRow).filter(
                SkuRow.tenant_id == tenant_id,
                SkuRow.id == sku_id,
            ).first()

            if not sku:
                failed_count += 1
                failed_items.append({
                    "sku_id": str(sku_id),
                    "reason": "SKU not found"
                })
                continue

            sku.status = status
            sku.updated_at = now
            sku.updated_by_user_id = membership_id
            sku.version += 1
            success_count += 1
        except Exception as exc:
            failed_count += 1
            failed_items.append({
                "sku_id": str(sku_id),
                "reason": str(exc)
            })

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "BATCH_UPDATE_FAILED",
            "批量更新失败",
            kind="conflict"
        ) from exc

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "total_count": len(sku_ids),
        "failed_items": failed_items,
    }
