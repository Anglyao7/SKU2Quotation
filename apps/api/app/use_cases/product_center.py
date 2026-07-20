from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..product_center_models import (
    AttributeDefinitionRow,
    ProductAuditEventRow,
    SkuRow,
    SupplierPriceRow,
)
from ..product_center_schemas import (
    AttributeDefinitionCreateRequest,
    AttributeDefinitionResponse,
    CategoryCreateRequest,
    CategoryResponse,
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
    SkuResponse,
    SkuUpdateRequest,
    SupplierPriceCreateRequest,
    SupplierPriceResponse,
)
from ..product_supplier_models import ProductCategoryRow
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
            ProductCategorySummary(id=category.id, code=category.code, name=category.name)
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
        setattr(row, field, value)
    row.version += 1
    row.updated_by_user_id = user_id
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
            path=row.path,
            status=row.status,
            version=row.version,
        )
        for row in repository.list_categories(session, tenant_id=tenant_id)
    ]


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
    path = f"{parent.path or parent.code}/{request.code}" if parent else request.code
    row = ProductCategoryRow(
        tenant_id=tenant_id,
        parent_id=request.parent_id,
        code=request.code,
        name=request.name,
        path=path,
        sort_order=request.sort_order,
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
    return CategoryResponse(
        id=row.id,
        parent_id=row.parent_id,
        code=row.code,
        name=row.name,
        sort_order=row.sort_order,
        path=row.path,
        status=row.status,
        version=row.version,
    )


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
