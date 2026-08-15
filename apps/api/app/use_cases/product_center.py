from __future__ import annotations

import io
import os
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..db_models import SupplierRow
from ..model_mixins import mark_deleted, utcnow
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
    CategoryDeleteImpactResponse,
    CategoryDeleteResponse,
    CategoryImportResponse,
    CategoryLayoutResponse,
    CategoryLayoutUpdateRequest,
    CategoryReorderRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    ManualProductCreateRequest,
    ProductAttributeResponse,
    ProductAuditEventResponse,
    ProductCard,
    ProductCategorySummary,
    ProductDetail,
    ProductImageResponse,
    ProductListPage,
    ProductOfferSummary,
    PublicCatalogOfferResponse,
    PublicCatalogOfferUpsertRequest,
    ProductReviewQueueItem,
    ReviewQueueField,
    SkuBatchCreateRequest,
    SkuCatalogExportRequest,
    SkuListItem,
    SkuListPage,
    SkuResponse,
    SkuSupplierSummary,
    SkuUpdateRequest,
    SupplierPriceCreateRequest,
    SupplierPriceResponse,
)
from ..product_supplier_models import (
    ProductAttributeRow,
    ProductCategoryRow,
    ProductImageRow,
    ProductRow,
)
from ..identity_models import TenantRow
from ..public_catalog_models import PublicCatalogOfferRow, TenantPublicProfileRow
from ..repositories import product_center_repository as repository
from ..services import query_cache
from ..services.category_template_import import (
    CategoryTemplateParseResult,
    category_name_key,
)
from ..services.external_image_migration import (
    ImageMigrationError,
    SourcePolicy,
    download_image,
)
from ..adapters.object_storage import get_object_storage
from ..services.sku_catalog_export import build_sku_catalog_workbook
from ..services.sku_quotas import ensure_sku_capacity
from ..services.sku_codes import issue_sku_codes
from ..services.catalog_write_guard import (
    lock_catalog_write as _lock_catalog_write,
    release_rollback_ownership as _release_rollback_ownership,
)


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

SKU_PACKING_QUANTITY_KEYS = (
    "装箱数",
    "一箱个数",
    "packing_quantity",
    "units_per_carton",
)


def _packing_quantity(option_values: dict[str, Any] | None) -> str | None:
    for key in SKU_PACKING_QUANTITY_KEYS:
        value = (option_values or {}).get(key)
        if value not in (None, ""):
            return str(value).strip() or None
    return None


def _with_packing_quantity(
    option_values: dict[str, Any],
    packing_quantity: Decimal | None,
    *,
    preserve_existing_when_unset: bool = False,
) -> dict[str, Any]:
    values = dict(option_values)
    if packing_quantity is None and preserve_existing_when_unset:
        existing = _packing_quantity(values)
        if existing is None:
            return values
        for key in SKU_PACKING_QUANTITY_KEYS:
            values.pop(key, None)
        values["装箱数"] = existing
        return values
    for key in SKU_PACKING_QUANTITY_KEYS:
        values.pop(key, None)
    if packing_quantity is not None:
        values["装箱数"] = format(packing_quantity, "f")
    return values

MAX_PRODUCT_IMAGE_BYTES = max(
    1,
    int(os.getenv("PRODUCT_IMAGE_MAX_BYTES", str(20 * 1024 * 1024))),
)
MAX_PRODUCT_IMAGE_EDGE = max(
    320,
    int(os.getenv("PRODUCT_IMAGE_MAX_EDGE", "2400")),
)
MAX_CATEGORY_COVER_BYTES = max(
    1,
    int(os.getenv("CATEGORY_COVER_MAX_BYTES", str(20 * 1024 * 1024))),
)
MAX_SKU_EXPORT_ROWS = max(
    1,
    int(os.getenv("SKU_EXPORT_MAX_ROWS", "100000")),
)


def _storefront_slug(session: Session, *, tenant_id: UUID) -> str | None:
    slug = session.scalar(
        select(TenantPublicProfileRow.slug).where(
            TenantPublicProfileRow.tenant_id == tenant_id
        )
    )
    if slug:
        return slug
    tenant = session.get(TenantRow, tenant_id)
    return tenant.slug if tenant is not None else None


def _sku_thumbnail_url(
    image: ProductImageRow,
    *,
    storefront_slug: str | None,
) -> str | None:
    object_key = str(image.object_key or "").strip()
    if not object_key:
        return None
    if object_key.startswith(("https://", "http://")):
        return object_key

    media_base_url = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
    if media_base_url:
        return f"{media_base_url}/{quote(object_key.lstrip('/'), safe='/')}"

    # The public media endpoint deliberately serves approved images only.
    # Source images without a public storage URL keep the existing placeholder.
    if image.approval_status != "APPROVED" or not storefront_slug:
        return None
    return f"/api/store/{quote(storefront_slug, safe='')}/media/{image.id}"


def _absolute_image_url(
    image: ProductImageRow,
    *,
    storefront_slug: str | None,
) -> str:
    url = _sku_thumbnail_url(image, storefront_slug=storefront_slug) or ""
    if not url.startswith("/"):
        return url
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return f"{public_base_url}{url}" if public_base_url else url


def _image_response(
    image: ProductImageRow,
    *,
    storefront_slug: str | None,
) -> ProductImageResponse:
    return ProductImageResponse(
        id=image.id,
        product_id=image.product_id,
        url=_sku_thumbnail_url(image, storefront_slug=storefront_slug) or "",
        original_filename=image.original_filename,
        content_type=image.content_type,
        byte_size=image.byte_size,
        width=image.width,
        height=image.height,
        image_role=image.image_role,
        approval_status=image.approval_status,
        created_at=image.created_at,
    )

SKU_STATUSES = frozenset({"DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"})
PRODUCT_STATUSES = frozenset({"DRAFT", "IN_REVIEW", "ACTIVE", "ARCHIVED"})


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


def _sku_source_type(
    sku: SkuRow,
    *,
    source_filename: str | None,
) -> str:
    if source_filename:
        return "PRODUCT_TEMPLATE"
    marker = sku.option_values.get(SKU_TEMPLATE_SOURCE_OPTION_KEY)
    if isinstance(marker, dict) and marker.get("source") == "PRODUCT_TEMPLATE":
        return "LEGACY_IMPORT"
    return "MANUAL"


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
        source_sku_code=row.source_sku_code,
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
    storefront_slug: str | None,
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
    primary_image = images[0] if images else None
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
        primary_image_url=(
            _sku_thumbnail_url(
                primary_image,
                storefront_slug=storefront_slug,
            )
            if primary_image is not None
            else None
        ),
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
    storefront_slug = _storefront_slug(session, tenant_id=tenant_id)
    return [
        _card(
            session,
            tenant_id=tenant_id,
            product=row,
            permissions=permissions,
            storefront_slug=storefront_slug,
        )
        for row in rows
    ]


def list_product_page(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    query: str,
    category_id: UUID | None,
    statuses: list[str],
    missing_images_only: bool,
    page: int,
    page_size: int,
) -> ProductListPage:
    """List the catalog by product, including products without any SKU rows."""

    _require(permissions, "product.view")
    normalized_statuses = sorted(
        {status.strip().upper() for status in statuses if status.strip()}
    )
    invalid_statuses = set(normalized_statuses) - PRODUCT_STATUSES
    if invalid_statuses:
        raise ApplicationError(
            "PRODUCT_STATUS_INVALID",
            f"Unsupported product status: {', '.join(sorted(invalid_statuses))}",
        )

    rows, total = repository.list_product_page_rows(
        session,
        tenant_id=tenant_id,
        query=query,
        category_id=category_id,
        statuses=normalized_statuses,
        missing_images_only=missing_images_only,
        page=page,
        page_size=page_size,
    )
    storefront_slug = _storefront_slug(session, tenant_id=tenant_id)
    items = [
        _card(
            session,
            tenant_id=tenant_id,
            product=row,
            permissions=permissions,
            storefront_slug=storefront_slug,
        )
        for row in rows
    ]
    return ProductListPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=(total + page_size - 1) // page_size,
    )


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
    missing_images_only: bool = False,
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

    cache_slot = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_CATALOG,
        identity={
            "kind": "sku-page",
            "query": query.casefold().strip(),
            "category_id": str(category_id) if category_id else None,
            "statuses": normalized_statuses,
            "missing_images_only": missing_images_only,
            "page": page,
            "page_size": page_size,
            "include_supplier_summary": include_supplier_summary,
        },
    )
    if cache_slot.hit:
        try:
            return SkuListPage.model_validate(cache_slot.value)
        except (TypeError, ValueError):
            pass

    count_cache_slot = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_CATALOG,
        identity={
            "kind": "sku-count",
            "query": query.casefold().strip(),
            "category_id": str(category_id) if category_id else None,
            "statuses": normalized_statuses,
            "missing_images_only": missing_images_only,
        },
    )
    known_total = (
        int(count_cache_slot.value)
        if count_cache_slot.hit
        and isinstance(count_cache_slot.value, int)
        and not isinstance(count_cache_slot.value, bool)
        and count_cache_slot.value >= 0
        else None
    )

    rows, total = repository.list_sku_page_rows(
        session,
        tenant_id=tenant_id,
        query=query,
        category_id=category_id,
        statuses=normalized_statuses,
        missing_images_only=missing_images_only,
        page=page,
        page_size=page_size,
        known_total=known_total,
    )
    if known_total is None:
        query_cache.store(
            count_cache_slot,
            total,
            ttl_seconds=query_cache.configured_ttl(
                "QUERY_CACHE_CATALOG_TTL_SECONDS",
                30,
                maximum=300,
            ),
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

    storefront_slug = _storefront_slug(session, tenant_id=tenant_id)

    image_statuses_by_product: dict[UUID, set[str]] = {}
    thumbnail_urls_by_product: dict[UUID, str] = {}
    for image in repository.list_images_for_products(
        session,
        tenant_id=tenant_id,
        product_ids=product_ids,
    ):
        image_statuses_by_product.setdefault(image.product_id, set()).add(
            image.approval_status
        )
        if image.product_id not in thumbnail_urls_by_product:
            thumbnail_url = _sku_thumbnail_url(
                image,
                storefront_slug=storefront_slug,
            )
            if thumbnail_url:
                thumbnail_urls_by_product[image.product_id] = thumbnail_url

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
                source_sku_code=row.sku.source_sku_code,
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
                packing_quantity=_packing_quantity(row.sku.option_values),
                public_price=offer.unit_price if offer else None,
                public_currency=offer.currency if offer else None,
                public_offer_status=offer.publication_status if offer else None,
                status=row.sku.status,
                version=row.sku.version,
                updated_at=row.sku.updated_at,
                source_type=_sku_source_type(
                    row.sku,
                    source_filename=row.source_filename,
                ),
                source_filename=row.source_filename,
                source_imported_at=row.source_imported_at,
                image_status=image_status,
                thumbnail_url=thumbnail_urls_by_product.get(row.product.id),
                is_pinned=row.product.storefront_pinned_at is not None,
            )
        )

    response = SkuListPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=(total + page_size - 1) // page_size,
    )
    query_cache.store(
        cache_slot,
        response.model_dump(mode="json"),
        ttl_seconds=query_cache.configured_ttl(
            "QUERY_CACHE_CATALOG_TTL_SECONDS",
            30,
            maximum=300,
        ),
    )
    return response


def export_sku_catalog(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: SkuCatalogExportRequest,
) -> bytes:
    _require(permissions, "product.view")
    rows, total = repository.list_sku_page_rows(
        session,
        tenant_id=tenant_id,
        query=request.q,
        category_id=request.category_id,
        statuses=list(request.statuses),
        missing_images_only=request.missing_images_only,
        page=1,
        page_size=MAX_SKU_EXPORT_ROWS + 1,
        sku_ids=set(request.sku_ids) if request.sku_ids else None,
    )
    if total > MAX_SKU_EXPORT_ROWS:
        raise ApplicationError(
            "SKU_EXPORT_TOO_LARGE",
            f"当前结果包含 {total} 个 SKU，请先按分类或状态筛选后再导出。",
            kind="too_large",
        )

    product_ids = {row.product.id for row in rows}
    images_by_product: dict[UUID, list[ProductImageRow]] = {}
    ordered_product_ids = list(product_ids)
    for start in range(0, len(ordered_product_ids), 1000):
        for image in repository.list_images_for_products(
            session,
            tenant_id=tenant_id,
            product_ids=set(ordered_product_ids[start : start + 1000]),
        ):
            images_by_product.setdefault(image.product_id, []).append(image)

    supplier_rows = repository.list_suppliers_by_ids(
        session,
        tenant_id=tenant_id,
        supplier_ids={
            row.sku.supplier_id
            for row in rows
            if row.sku.supplier_id is not None
        },
    )
    supplier_names = {row.id: row.name for row in supplier_rows}
    storefront_slug = _storefront_slug(session, tenant_id=tenant_id)
    image_urls = {
        image.id: _absolute_image_url(image, storefront_slug=storefront_slug)
        for images in images_by_product.values()
        for image in images
    }
    return build_sku_catalog_workbook(
        rows=rows,
        images_by_product=images_by_product,
        image_urls=image_urls,
        supplier_names=supplier_names,
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
    card = _card(
        session,
        tenant_id=tenant_id,
        product=product,
        permissions=permissions,
        storefront_slug=_storefront_slug(session, tenant_id=tenant_id),
    )
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


def _normalized_product_image(content: bytes) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            image.thumbnail(
                (MAX_PRODUCT_IMAGE_EDGE, MAX_PRODUCT_IMAGE_EDGE),
                Image.Resampling.LANCZOS,
            )
            has_alpha = "A" in image.getbands() or (
                image.mode == "P" and "transparency" in image.info
            )
            normalized = image.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=90, method=4)
            return output.getvalue(), normalized.width, normalized.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ApplicationError(
            "PRODUCT_IMAGE_INVALID",
            "图片无法识别，请上传 PNG、JPG 或 WebP 文件。",
        ) from exc


def upload_product_main_image(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
    filename: str | None,
    content: bytes,
) -> ProductImageResponse:
    _require(permissions, "product.edit")
    if not content:
        raise ApplicationError("PRODUCT_IMAGE_EMPTY", "请选择一张商品图片。")
    if len(content) > MAX_PRODUCT_IMAGE_BYTES:
        raise ApplicationError(
            "PRODUCT_IMAGE_TOO_LARGE",
            f"商品图片不能超过 {MAX_PRODUCT_IMAGE_BYTES // (1024 * 1024)} MB。",
            kind="too_large",
        )
    _lock_catalog_write(session, tenant_id=tenant_id)
    product = repository.get_product_row(
        session,
        tenant_id=tenant_id,
        product_id=product_id,
    )
    if product is None:
        raise ApplicationError(
            "PRODUCT_NOT_FOUND",
            "Product was not found.",
            kind="not_found",
        )
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        product_ids=[product.id],
    )

    processed, width, height = _normalized_product_image(content)
    image_id = uuid4()
    object_key = f"tenants/{tenant_id}/products/{product_id}/images/{image_id}.webp"
    storage = get_object_storage()
    try:
        with tempfile.NamedTemporaryFile(suffix=".webp") as temporary:
            temporary.write(processed)
            temporary.flush()
            storage.put_file(
                Path(temporary.name),
                object_key=object_key,
                content_type="image/webp",
            )
    except Exception as exc:
        raise ApplicationError(
            "PRODUCT_IMAGE_STORAGE_UNAVAILABLE",
            "图片上传到对象存储失败，请稍后重试。",
            kind="unavailable",
        ) from exc

    now = utcnow()
    previous_main_images = [
        image
        for image in repository.list_images(
            session,
            tenant_id=tenant_id,
            product_id=product_id,
        )
        if image.image_role == "MAIN"
    ]
    for previous in previous_main_images:
        mark_deleted(previous, at=now)

    image = ProductImageRow(
        id=image_id,
        tenant_id=tenant_id,
        product_id=product_id,
        storage_provider=storage.backend_name.upper(),
        bucket=os.getenv("OBJECT_STORAGE_BUCKET", "local") or "local",
        object_key=object_key,
        original_filename=(filename or f"{product.name}.webp")[:500],
        content_type="image/webp",
        byte_size=len(processed),
        sha256=sha256(processed).hexdigest(),
        width=width,
        height=height,
        image_role="MAIN",
        sort_order=0,
        approval_status="APPROVED",
        alt_text=product.name,
        created_by=user_id,
    )
    session.add(image)
    product.current_version += 1
    product.updated_by = user_id
    product.updated_at = now
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=product.id,
            entity_type="PRODUCT",
            entity_id=str(product.id),
            action="product.image.uploaded",
            before={
                "main_image_ids": [str(previous.id) for previous in previous_main_images],
            },
            after={
                "image_id": str(image.id),
                "object_key": image.object_key,
                "width": width,
                "height": height,
            },
            actor_membership_id=membership_id,
            occurred_at=now,
        )
    )
    try:
        _commit(
            session,
            conflict_code="PRODUCT_IMAGE_CONFLICT",
            conflict_message="Product image could not be indexed.",
        )
    except Exception:
        try:
            storage.delete(object_key)
        except Exception:
            pass
        raise
    session.refresh(image)
    return _image_response(
        image,
        storefront_slug=_storefront_slug(session, tenant_id=tenant_id),
    )


_PRODUCT_IMAGE_DOWNLOAD_EXTENSIONS = {
    "image/avif": "avif",
    "image/bmp": "bmp",
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def _product_image_download_filename(
    *,
    product: ProductRow,
    image: ProductImageRow,
    content_type: str,
) -> str:
    source_name = Path(image.original_filename or product.name or "product-image").stem
    safe_stem = "".join(
        character
        for character in source_name
        if character not in {"/", "\\", "\r", "\n", "\t"}
        and ord(character) >= 32
    ).strip(" .")[:120]
    extension = _PRODUCT_IMAGE_DOWNLOAD_EXTENSIONS.get(content_type, "bin")
    return f"{safe_stem or 'product-image'}.{extension}"


def download_product_main_image(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
) -> tuple[bytes, str, str]:
    _require(permissions, "product.view")
    product = repository.get_product_row(
        session,
        tenant_id=tenant_id,
        product_id=product_id,
    )
    if product is None:
        raise ApplicationError(
            "PRODUCT_NOT_FOUND",
            "Product was not found.",
            kind="not_found",
        )
    images = repository.list_images(
        session,
        tenant_id=tenant_id,
        product_id=product_id,
    )
    image = next(
        (candidate for candidate in images if candidate.image_role == "MAIN"),
        images[0] if images else None,
    )
    if image is None or not str(image.object_key or "").strip():
        raise ApplicationError(
            "PRODUCT_IMAGE_NOT_FOUND",
            "该商品还没有可下载的图片。",
            kind="not_found",
        )

    object_key = str(image.object_key).strip()
    if object_key.startswith(("https://", "http://")):
        try:
            with tempfile.TemporaryDirectory(prefix="atc-image-download-") as directory:
                target = Path(directory) / "source-image"
                with httpx.Client(
                    timeout=httpx.Timeout(20.0, connect=5.0),
                    follow_redirects=False,
                ) as client:
                    metadata = download_image(
                        client,
                        source_url=object_key,
                        destination=target,
                        policy=SourcePolicy((), allow_all_public_hosts=True),
                        max_bytes=MAX_PRODUCT_IMAGE_BYTES,
                        max_pixels=100_000_000,
                        max_redirects=4,
                    )
                content = target.read_bytes()
        except (ImageMigrationError, OSError) as exc:
            raise ApplicationError(
                "PRODUCT_IMAGE_DOWNLOAD_UNAVAILABLE",
                "原图片暂时无法下载，请稍后重试。",
                kind="unavailable",
            ) from exc
        content_type = metadata.content_type
    else:
        try:
            with get_object_storage().materialize(object_key) as path:
                byte_size = path.stat().st_size
                if byte_size > MAX_PRODUCT_IMAGE_BYTES:
                    raise ApplicationError(
                        "PRODUCT_IMAGE_TOO_LARGE",
                        f"商品图片不能超过 {MAX_PRODUCT_IMAGE_BYTES // (1024 * 1024)} MB。",
                        kind="too_large",
                    )
                content = path.read_bytes()
        except ApplicationError:
            raise
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ApplicationError(
                "PRODUCT_IMAGE_DOWNLOAD_UNAVAILABLE",
                "图片文件暂时不可用，请稍后重试。",
                kind="unavailable",
            ) from exc
        content_type = (
            image.content_type
            if str(image.content_type or "").startswith("image/")
            else "application/octet-stream"
        )

    if not content:
        raise ApplicationError(
            "PRODUCT_IMAGE_DOWNLOAD_UNAVAILABLE",
            "图片文件暂时不可用，请稍后重试。",
            kind="unavailable",
        )
    return (
        content,
        content_type,
        _product_image_download_filename(
            product=product,
            image=image,
            content_type=content_type,
        ),
    )


def create_manual_product(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: ManualProductCreateRequest,
) -> ProductDetail:
    _require(permissions, "product.view")
    _require(permissions, "product.edit")
    _require(permissions, "catalog.publish")
    _lock_catalog_write(session, tenant_id=tenant_id)
    tenant = session.get(TenantRow, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")

    category = repository.get_category(
        session,
        tenant_id=tenant_id,
        category_id=request.category_id,
    )
    if request.category_id is not None and category is None:
        raise ApplicationError(
            "CATEGORY_NOT_FOUND",
            "Product category was not found.",
            kind="not_found",
        )
    if category is not None and category.status != "ACTIVE":
        raise ApplicationError(
            "CATEGORY_NOT_ACTIVE",
            "Archived or inactive categories cannot receive new products.",
            kind="conflict",
        )
    if request.product_code and repository.product_code_exists(
        session,
        tenant_id=tenant_id,
        product_code=request.product_code,
    ):
        raise ApplicationError(
            "PRODUCT_CODE_CONFLICT",
            "Product code already exists.",
            kind="conflict",
        )

    source_sku_code = request.sku_code
    if source_sku_code is not None and repository.source_sku_code_exists(
        session,
        tenant_id=tenant_id,
        source_sku_code=source_sku_code,
    ):
        raise ApplicationError(
            "SOURCE_SKU_CODE_CONFLICT",
            f"Source SKU code already exists: {source_sku_code}",
            kind="conflict",
        )

    ensure_sku_capacity(session, tenant_id=tenant_id, additional=1)

    now = utcnow()
    product_status = "ACTIVE" if request.publish_to_storefront else "DRAFT"
    sku_status = "ACTIVE" if request.publish_to_storefront else "DRAFT"
    offer_status = "PUBLISHED" if request.publish_to_storefront else "DRAFT"
    product = ProductRow(
        id=uuid4(),
        tenant_id=tenant_id,
        product_code=request.product_code,
        name=request.name,
        description=request.description,
        category_id=category.id if category is not None else None,
        status=product_status,
        default_unit=request.default_unit,
        search_document_version=0,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(product)
    session.flush()

    sku_code, sku_sequence = issue_sku_codes(
        session,
        tenant=tenant,
        product=product,
        count=1,
        issued_at=now,
    )[0]

    sku = SkuRow(
        id=uuid4(),
        tenant_id=tenant_id,
        product_id=product.id,
        sku_code=sku_code,
        source_sku_code=source_sku_code,
        sku_sequence=sku_sequence,
        name=request.sku_name or request.name,
        option_values=_with_packing_quantity({}, request.packing_quantity),
        barcode=request.barcode,
        default_moq=request.default_moq,
        moq_unit=request.moq_unit,
        weight=request.weight,
        weight_unit=request.weight_unit,
        status=sku_status,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    session.add(sku)
    session.flush()

    offer = PublicCatalogOfferRow(
        id=uuid4(),
        tenant_id=tenant_id,
        sku_id=sku.id,
        unit_price=request.unit_price,
        currency=request.currency,
        tags=request.tags,
        display_tag=request.display_tag,
        tag_color=request.tag_color,
        publication_status=offer_status,
        published_at=now if offer_status == "PUBLISHED" else None,
    )
    session.add(offer)

    if request.image_url:
        session.add(
            ProductImageRow(
                id=uuid4(),
                tenant_id=tenant_id,
                product_id=product.id,
                storage_provider="EXTERNAL",
                bucket="external",
                object_key=request.image_url,
                original_filename=None,
                content_type="image/remote",
                byte_size=0,
                sha256=sha256(request.image_url.encode("utf-8")).hexdigest(),
                image_role="MAIN",
                sort_order=0,
                approval_status="APPROVED",
                alt_text=request.name,
                created_by=user_id,
            )
        )

    request_snapshot = request.model_dump(mode="json")
    session.add_all(
        [
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product.id,
                entity_type="PRODUCT",
                entity_id=str(product.id),
                action="product.created",
                before={},
                after={
                    "name": product.name,
                    "product_code": product.product_code,
                    "description": product.description,
                    "category_id": str(product.category_id) if product.category_id else None,
                    "status": product.status,
                    "default_unit": product.default_unit,
                    "image_url": request.image_url,
                },
                actor_membership_id=membership_id,
                occurred_at=now,
            ),
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product.id,
                entity_type="SKU",
                entity_id=str(sku.id),
                action="sku.created",
                before={},
                after={
                    "sku_code": sku.sku_code,
                    "source_sku_code": sku.source_sku_code,
                    "name": sku.name,
                    "barcode": sku.barcode,
                    "default_moq": request_snapshot["default_moq"],
                    "moq_unit": sku.moq_unit,
                    "packing_quantity": request_snapshot["packing_quantity"],
                    "weight": request_snapshot["weight"],
                    "weight_unit": sku.weight_unit,
                    "status": sku.status,
                },
                actor_membership_id=membership_id,
                occurred_at=now,
            ),
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product.id,
                entity_type="SKU",
                entity_id=str(sku.id),
                action=f"public_offer.{offer_status.casefold()}",
                before={},
                after={
                    "unit_price": request_snapshot["unit_price"],
                    "currency": offer.currency,
                    "tags": offer.tags,
                    "display_tag": offer.display_tag,
                    "tag_color": offer.tag_color,
                    "publication_status": offer.publication_status,
                },
                actor_membership_id=membership_id,
                occurred_at=now,
            ),
        ]
    )
    _commit(
        session,
        conflict_code="MANUAL_PRODUCT_CONFLICT",
        conflict_message="Product or SKU code already exists.",
    )
    return get_product(
        session,
        tenant_id=tenant_id,
        permissions=permissions,
        product_id=product.id,
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
    _lock_catalog_write(session, tenant_id=tenant_id)
    product = repository.get_product_row(session, tenant_id=tenant_id, product_id=product_id)
    if product is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    tenant = session.get(TenantRow, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")
    definitions = repository.list_attribute_definitions(
        session, tenant_id=tenant_id, category_id=product.category_id
    )
    variant_keys = {row.attribute_key for row in definitions if row.is_variant and row.status == "ACTIVE"}
    for item in request.items:
        if item.sku_code is not None and repository.source_sku_code_exists(
            session,
            tenant_id=tenant_id,
            source_sku_code=item.sku_code,
        ):
            raise ApplicationError(
                "SOURCE_SKU_CODE_CONFLICT",
                f"Source SKU code already exists: {item.sku_code}",
                kind="conflict",
            )
        # Older clients stored carton quantity alongside variant attributes.
        # It is operational SKU metadata rather than a category-owned variant,
        # so accept the known aliases here and canonicalize them below.
        invalid_keys = (
            set(item.option_values)
            - variant_keys
            - set(SKU_PACKING_QUANTITY_KEYS)
        )
        if invalid_keys:
            raise ApplicationError(
                "SKU_VARIANT_ATTRIBUTE_INVALID",
                f"Variant attributes are not allowed by the category template: {', '.join(sorted(invalid_keys))}",
            )
    ensure_sku_capacity(
        session,
        tenant_id=tenant_id,
        additional=len(request.items),
    )
    rows: list[SkuRow] = []
    now = utcnow()
    issued_codes = issue_sku_codes(
        session,
        tenant=tenant,
        product=product,
        count=len(request.items),
        issued_at=now,
    )
    for item, (sku_code, sku_sequence) in zip(
        request.items,
        issued_codes,
        strict=True,
    ):
        row = SkuRow(
            tenant_id=tenant_id,
            product_id=product_id,
            sku_code=sku_code,
            source_sku_code=item.sku_code,
            sku_sequence=sku_sequence,
            name=item.name,
            option_values=_with_packing_quantity(
                item.option_values,
                item.packing_quantity,
                preserve_existing_when_unset=True,
            ),
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
    _lock_catalog_write(session, tenant_id=tenant_id)
    row = repository.get_sku(session, tenant_id=tenant_id, sku_id=sku_id)
    if row is None:
        raise ApplicationError("SKU_NOT_FOUND", "SKU was not found.", kind="not_found")
    if row.version != request.expected_version:
        raise ApplicationError(
            "SKU_VERSION_CONFLICT",
            "SKU has been changed by another user.",
            kind="conflict",
        )
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        sku_ids=[row.id],
    )
    before = _sku_response(row).model_dump(mode="json")
    changes = request.model_dump(exclude={"expected_version"}, exclude_unset=True)
    packing_quantity_supplied = "packing_quantity" in changes
    packing_quantity = changes.pop("packing_quantity", None)
    option_values_supplied = "option_values" in changes
    for field, value in changes.items():
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
    if packing_quantity_supplied:
        row.option_values = _with_packing_quantity(
            row.option_values,
            packing_quantity,
        )
    elif option_values_supplied:
        row.option_values = _with_packing_quantity(
            row.option_values,
            None,
            preserve_existing_when_unset=True,
        )
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
    _lock_catalog_write(session, tenant_id=tenant_id)
    sku = repository.get_sku(session, tenant_id=tenant_id, sku_id=sku_id)
    if sku is None:
        raise ApplicationError("SKU_NOT_FOUND", "SKU was not found.", kind="not_found")
    product = repository.get_product_row(
        session, tenant_id=tenant_id, product_id=sku.product_id
    )
    if product is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        sku_ids=[sku.id],
    )
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
    cache_slot = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_METADATA,
        identity={"kind": "categories", "schema": 2},
    )
    if cache_slot.hit and isinstance(cache_slot.value, list):
        try:
            return [CategoryResponse.model_validate(row) for row in cache_slot.value]
        except (TypeError, ValueError):
            pass
    response = _category_responses(
        session,
        tenant_id=tenant_id,
        rows=repository.list_categories(session, tenant_id=tenant_id),
    )
    query_cache.store(
        cache_slot,
        [row.model_dump(mode="json") for row in response],
        ttl_seconds=query_cache.configured_ttl(
            "QUERY_CACHE_METADATA_TTL_SECONDS",
            300,
            maximum=1_800,
        ),
    )
    return response


def get_category_layout(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> CategoryLayoutResponse:
    _require(permissions, "product.view")
    cache_slot = query_cache.lookup(
        tenant_id=tenant_id,
        domain=query_cache.DOMAIN_METADATA,
        identity={"kind": "category-layout"},
    )
    if cache_slot.hit:
        try:
            return CategoryLayoutResponse.model_validate(cache_slot.value)
        except (TypeError, ValueError):
            pass
    root_count = len(
        repository.list_sibling_categories(
            session, tenant_id=tenant_id, parent_id=None
        )
    )
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id
        )
    )
    position = min(
        max(0, int(profile.all_products_position or 0)) if profile else 0,
        root_count,
    )
    response = CategoryLayoutResponse(
        all_products_position=position,
        root_category_count=root_count,
        category_showcase_enabled=(
            bool(profile.category_showcase_enabled) if profile else True
        ),
    )
    query_cache.store(
        cache_slot,
        response.model_dump(mode="json"),
        ttl_seconds=query_cache.configured_ttl(
            "QUERY_CACHE_METADATA_TTL_SECONDS",
            300,
            maximum=1_800,
        ),
    )
    return response


def update_category_layout(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    request: CategoryLayoutUpdateRequest,
) -> CategoryLayoutResponse:
    _require(permissions, "product.edit")
    root_count = len(
        repository.list_sibling_categories(
            session, tenant_id=tenant_id, parent_id=None
        )
    )
    if request.all_products_position > root_count:
        raise ApplicationError(
            "CATEGORY_LAYOUT_POSITION_INVALID",
            "“全部商品”的位置超出当前一级分类数量，请刷新后重试。",
            kind="conflict",
        )
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id
        )
    )
    if profile is None:
        tenant = session.get(TenantRow, tenant_id)
        if tenant is None:
            raise ApplicationError(
                "TENANT_NOT_FOUND",
                "Merchant workspace was not found.",
                kind="not_found",
            )
        profile = TenantPublicProfileRow(
            tenant_id=tenant_id,
            slug=tenant.slug,
            publication_status=(
                "PUBLISHED" if tenant.status == "active" else "SUSPENDED"
            ),
        )
        session.add(profile)
        session.flush()
    previous = max(0, int(profile.all_products_position or 0))
    previous_showcase_enabled = bool(profile.category_showcase_enabled)
    profile.all_products_position = request.all_products_position
    profile.category_showcase_enabled = request.category_showcase_enabled
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="CATEGORY",
            entity_id=str(tenant_id),
            action="category_layout.updated",
            before={
                "all_products_position": previous,
                "category_showcase_enabled": previous_showcase_enabled,
            },
            after={
                "all_products_position": request.all_products_position,
                "category_showcase_enabled": request.category_showcase_enabled,
            },
            actor_membership_id=membership_id,
        )
    )
    _commit(
        session,
        conflict_code="CATEGORY_LAYOUT_CONFLICT",
        conflict_message="分类入口顺序保存失败，请刷新后重试。",
    )
    return CategoryLayoutResponse(
        all_products_position=request.all_products_position,
        root_category_count=root_count,
        category_showcase_enabled=request.category_showcase_enabled,
    )


def _category_response(
    row: ProductCategoryRow,
    *,
    product_count: int = 0,
    uploaded_cover_image_url: str | None = None,
    cover_product_name: str | None = None,
    cover_product_image_url: str | None = None,
) -> CategoryResponse:
    cover_source = str(row.cover_source or "NONE").upper()
    cover_image_url = (
        uploaded_cover_image_url
        if cover_source == "UPLOAD"
        else cover_product_image_url
        if cover_source == "PRODUCT"
        else None
    )
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
        product_count=product_count,
        cover_source=cover_source,
        cover_product_id=row.cover_product_id,
        cover_product_name=cover_product_name,
        cover_image_url=cover_image_url,
        uploaded_cover_image_url=uploaded_cover_image_url,
        cover_product_image_url=cover_product_image_url,
    )


def _category_responses(
    session: Session,
    *,
    tenant_id: UUID,
    rows: list[ProductCategoryRow],
) -> list[CategoryResponse]:
    if not rows:
        return []
    category_ids = {row.id for row in rows}
    children_by_parent: dict[UUID, list[UUID]] = {}
    for row in rows:
        if row.parent_id is not None:
            children_by_parent.setdefault(row.parent_id, []).append(row.id)
    for row in rows:
        if row.parent_id is not None:
            continue
        if row.id in children_by_parent:
            continue
        child_ids = [
            child.id
            for child in repository.list_child_categories(
                session,
                tenant_id=tenant_id,
                parent_id=row.id,
            )
        ]
        if child_ids:
            children_by_parent[row.id] = child_ids
            category_ids.update(child_ids)
    product_counts = repository.product_counts_by_category(
        session,
        tenant_id=tenant_id,
        category_ids=list(category_ids),
    )
    # A product assigned to a second-level category is also associated with
    # its first-level category in the managed hierarchy.
    for parent_id, child_ids in children_by_parent.items():
        product_counts[parent_id] = product_counts.get(parent_id, 0) + sum(
            product_counts.get(child_id, 0) for child_id in child_ids
        )
    storefront_slug = _storefront_slug(session, tenant_id=tenant_id)
    product_ids = {
        row.cover_product_id for row in rows if row.cover_product_id is not None
    }
    products_by_id = {
        product.id: product
        for product in session.scalars(
            select(ProductRow).where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.id.in_(product_ids),
                ProductRow.deleted_at.is_(None),
            )
        ).all()
    } if product_ids else {}
    images_by_product_id: dict[UUID, ProductImageRow] = {}
    for image in repository.list_images_for_products(
        session,
        tenant_id=tenant_id,
        product_ids=product_ids,
    ):
        if image.approval_status == "APPROVED":
            images_by_product_id.setdefault(image.product_id, image)

    responses: list[CategoryResponse] = []
    for row in rows:
        uploaded_cover_image_url = None
        if row.cover_object_key and storefront_slug:
            media_base_url = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
            uploaded_cover_image_url = (
                f"{media_base_url}/{quote(row.cover_object_key.lstrip('/'), safe='/')}"
                if media_base_url
                else (
                    f"/api/store/{quote(storefront_slug, safe='')}/categories/"
                    f"{row.id}/cover?v={row.version}"
                )
            )
        product = products_by_id.get(row.cover_product_id)
        product_image = images_by_product_id.get(row.cover_product_id)
        responses.append(
            _category_response(
                row,
                product_count=product_counts.get(row.id, 0),
                uploaded_cover_image_url=uploaded_cover_image_url,
                cover_product_name=product.name if product is not None else None,
                cover_product_image_url=(
                    _sku_thumbnail_url(product_image, storefront_slug=storefront_slug)
                    if product_image is not None
                    else None
                ),
            )
        )
    return responses


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


def import_categories(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    parsed: CategoryTemplateParseResult,
) -> CategoryImportResponse:
    _require(permissions, "product.edit")
    existing_categories = repository.list_categories(session, tenant_id=tenant_id)
    existing_category_ids = {row.id for row in existing_categories}
    existing_roots_in_order = sorted(
        (row for row in existing_categories if row.parent_id is None),
        key=lambda row: (row.sort_order, category_name_key(row.name), str(row.id)),
    )
    existing_children_in_order: dict[UUID, list[ProductCategoryRow]] = {}
    for row in existing_categories:
        if row.parent_id is not None:
            existing_children_in_order.setdefault(row.parent_id, []).append(row)
    for rows in existing_children_in_order.values():
        rows.sort(
            key=lambda row: (
                row.sort_order,
                category_name_key(row.name),
                str(row.id),
            )
        )
    roots_by_name = {
        category_name_key(row.name): row
        for row in existing_categories
        if row.parent_id is None
    }
    children_by_parent: dict[UUID, dict[str, ProductCategoryRow]] = {}
    for row in existing_categories:
        if row.parent_id is None:
            continue
        children_by_parent.setdefault(row.parent_id, {})[
            category_name_key(row.name)
        ] = row

    primary_created = 0
    secondary_created = 0
    primary_existing = 0
    secondary_existing = 0

    uploaded_root_keys: list[str] = []
    uploaded_child_keys: dict[UUID, list[str]] = {}

    for root_position, group in enumerate(parsed.groups):
        root_key = category_name_key(group.primary_name)
        uploaded_root_keys.append(root_key)
        root = roots_by_name.get(root_key)
        if root is None:
            root_id = uuid4()
            root = ProductCategoryRow(
                id=root_id,
                tenant_id=tenant_id,
                parent_id=None,
                code=f"IMP-{root_id.hex.upper()}",
                name=group.primary_name,
                path=group.primary_name,
                sort_order=root_position,
                display_color=None,
                status="ACTIVE",
            )
            session.add(root)
            roots_by_name[root_key] = root
            children_by_parent[root.id] = {}
            primary_created += 1
            session.add(
                ProductAuditEventRow(
                    tenant_id=tenant_id,
                    product_id=None,
                    entity_type="CATEGORY",
                    entity_id=str(root.id),
                    action="category.imported",
                    before={},
                    after={
                        "parent_id": None,
                        "code": root.code,
                        "name": root.name,
                        "sort_order": root.sort_order,
                        "source": "CATEGORY_TEMPLATE",
                    },
                    actor_membership_id=membership_id,
                )
            )
        else:
            primary_existing += 1

        child_rows = children_by_parent.setdefault(root.id, {})
        uploaded_child_keys[root.id] = []
        for child_position, secondary_name in enumerate(group.secondary_names):
            child_key = category_name_key(secondary_name)
            uploaded_child_keys[root.id].append(child_key)
            if child_key in child_rows:
                secondary_existing += 1
                continue
            child_id = uuid4()
            child = ProductCategoryRow(
                id=child_id,
                tenant_id=tenant_id,
                parent_id=root.id,
                code=f"IMP-{child_id.hex.upper()}",
                name=secondary_name,
                path=f"{root.name}/{secondary_name}",
                sort_order=child_position,
                display_color=None,
                status="ACTIVE",
            )
            session.add(child)
            child_rows[child_key] = child
            secondary_created += 1
            session.add(
                ProductAuditEventRow(
                    tenant_id=tenant_id,
                    product_id=None,
                    entity_type="CATEGORY",
                    entity_id=str(child.id),
                    action="category.imported",
                    before={},
                    after={
                        "parent_id": str(root.id),
                        "code": child.code,
                        "name": child.name,
                        "sort_order": child.sort_order,
                        "source": "CATEGORY_TEMPLATE",
                    },
                    actor_membership_id=membership_id,
                )
            )

    def apply_import_order(row: ProductCategoryRow, position: int) -> None:
        if row.sort_order == position:
            return
        previous = row.sort_order
        row.sort_order = position
        if row.id not in existing_category_ids:
            return
        row.version += 1
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=None,
                entity_type="CATEGORY",
                entity_id=str(row.id),
                action="category.import_reordered",
                before={"sort_order": previous},
                after={
                    "sort_order": position,
                    "source": "CATEGORY_TEMPLATE",
                },
                actor_membership_id=membership_id,
            )
        )

    uploaded_root_key_set = set(uploaded_root_keys)
    ordered_roots = [roots_by_name[key] for key in uploaded_root_keys]
    ordered_roots.extend(
        row
        for row in existing_roots_in_order
        if category_name_key(row.name) not in uploaded_root_key_set
    )
    for position, root in enumerate(ordered_roots):
        apply_import_order(root, position)

    for root_key in uploaded_root_keys:
        root = roots_by_name[root_key]
        child_rows = children_by_parent.get(root.id, {})
        child_keys = uploaded_child_keys.get(root.id, [])
        uploaded_child_key_set = set(child_keys)
        ordered_children = [child_rows[key] for key in child_keys]
        ordered_children.extend(
            row
            for row in existing_children_in_order.get(root.id, [])
            if category_name_key(row.name) not in uploaded_child_key_set
        )
        for position, child in enumerate(ordered_children):
            apply_import_order(child, position)

    _commit(
        session,
        conflict_code="CATEGORY_IMPORT_CONFLICT",
        conflict_message="分类导入时数据已发生变化，请刷新后重新导入。",
    )
    return CategoryImportResponse(
        processed_rows=parsed.processed_rows,
        primary_created=primary_created,
        secondary_created=secondary_created,
        primary_existing=primary_existing,
        secondary_existing=secondary_existing,
        duplicate_rows_ignored=parsed.duplicate_rows_ignored,
        blank_rows_ignored=parsed.blank_rows_ignored,
    )


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
    return _category_responses(
        session,
        tenant_id=tenant_id,
        rows=[rows_by_id[item.id] for item in request.items],
    )


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
    if request.cover_source in {"UPLOAD", "PRODUCT"} and request.parent_id is None:
        raise ApplicationError(
            "CATEGORY_COVER_LEVEL_INVALID",
            "分类门面仅用于二级分类。",
            kind="conflict",
        )
    if request.cover_source == "UPLOAD" and not row.cover_object_key:
        raise ApplicationError(
            "CATEGORY_COVER_UPLOAD_REQUIRED",
            "请先上传分类图片。",
            kind="conflict",
        )
    if request.cover_source == "PRODUCT":
        cover_product = repository.get_product_row(
            session,
            tenant_id=tenant_id,
            product_id=request.cover_product_id,
        )
        if (
            cover_product is None
            or cover_product.category_id != row.id
            or cover_product.status == "ARCHIVED"
        ):
            raise ApplicationError(
                "CATEGORY_COVER_PRODUCT_INVALID",
                "只能选择当前二级分类内的商品作为门面。",
                kind="conflict",
            )
        if not any(
            image.approval_status == "APPROVED"
            for image in repository.list_images(
                session,
                tenant_id=tenant_id,
                product_id=cover_product.id,
            )
        ):
            raise ApplicationError(
                "CATEGORY_COVER_PRODUCT_IMAGE_REQUIRED",
                "该商品还没有可公开展示的图片，请先上传商品图片。",
                kind="conflict",
            )
    row.parent_id = request.parent_id
    row.name = request.name
    row.path = f"{parent.name}/{request.name}" if parent else request.name
    row.sort_order = request.sort_order
    row.status = request.status
    if parent is not None:
        row.display_color = None
    elif "display_color" in request.model_fields_set:
        row.display_color = request.display_color
    if request.parent_id is None:
        row.cover_source = "NONE"
        row.cover_product_id = None
    elif request.cover_source is not None:
        row.cover_source = request.cover_source
        row.cover_product_id = (
            request.cover_product_id if request.cover_source == "PRODUCT" else None
        )
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
    return _category_responses(session, tenant_id=tenant_id, rows=[row])[0]


def upload_category_cover(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    category_id: UUID,
    content: bytes,
) -> CategoryResponse:
    _require(permissions, "product.edit")
    if not content:
        raise ApplicationError("CATEGORY_COVER_EMPTY", "请选择一张分类图片。")
    if len(content) > MAX_CATEGORY_COVER_BYTES:
        raise ApplicationError(
            "CATEGORY_COVER_TOO_LARGE",
            f"分类图片不能超过 {MAX_CATEGORY_COVER_BYTES // (1024 * 1024)} MB。",
            kind="too_large",
        )
    category = repository.get_category(
        session,
        tenant_id=tenant_id,
        category_id=category_id,
    )
    if category is None:
        raise ApplicationError(
            "CATEGORY_NOT_FOUND", "分类不存在。", kind="not_found"
        )
    if category.parent_id is None:
        raise ApplicationError(
            "CATEGORY_COVER_LEVEL_INVALID",
            "分类门面仅用于二级分类。",
            kind="conflict",
        )

    processed, _width, _height = _normalized_product_image(content)
    object_key = (
        f"tenants/{tenant_id}/categories/{category_id}/cover/"
        f"{uuid4().hex}.webp"
    )
    storage = get_object_storage()
    try:
        with tempfile.NamedTemporaryFile(suffix=".webp") as temporary:
            temporary.write(processed)
            temporary.flush()
            storage.put_file(
                Path(temporary.name),
                object_key=object_key,
                content_type="image/webp",
            )
    except Exception as exc:
        raise ApplicationError(
            "CATEGORY_COVER_STORAGE_UNAVAILABLE",
            "分类图片上传到对象存储失败，请稍后重试。",
            kind="unavailable",
        ) from exc

    previous_object_key = str(category.cover_object_key or "").strip() or None
    before = _category_response(category).model_dump(mode="json")
    category.cover_object_key = object_key
    category.cover_source = "UPLOAD"
    category.cover_product_id = None
    category.version += 1
    after = _category_response(category).model_dump(mode="json")
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="CATEGORY",
            entity_id=str(category.id),
            action="category.cover_uploaded",
            before=before,
            after=after,
            actor_membership_id=membership_id,
        )
    )
    try:
        _commit(
            session,
            conflict_code="CATEGORY_COVER_CONFLICT",
            conflict_message="分类图片保存失败，请刷新后重试。",
        )
    except Exception:
        try:
            storage.delete(object_key)
        except Exception:
            pass
        raise
    if previous_object_key and previous_object_key != object_key:
        try:
            storage.delete(previous_object_key)
        except Exception:
            pass
    return _category_responses(
        session,
        tenant_id=tenant_id,
        rows=[category],
    )[0]


def _category_delete_scope(
    session: Session,
    *,
    tenant_id: UUID,
    category: ProductCategoryRow,
) -> list[ProductCategoryRow]:
    children = repository.list_child_categories(
        session,
        tenant_id=tenant_id,
        parent_id=category.id,
    )
    return [category, *children]


def _category_delete_counts(
    session: Session,
    *,
    tenant_id: UUID,
    categories: list[ProductCategoryRow],
) -> tuple[int, list[UUID], int]:
    category_ids = [row.id for row in categories]
    affected_product_count = int(
        session.scalar(
            select(func.count(ProductRow.id)).where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.category_id.in_(category_ids),
                ProductRow.deleted_at.is_(None),
                ProductRow.status != "ARCHIVED",
            )
        )
        or 0
    )
    attribute_definition_ids = list(
        session.scalars(
            select(AttributeDefinitionRow.id).where(
                AttributeDefinitionRow.tenant_id == tenant_id,
                AttributeDefinitionRow.category_id.in_(category_ids),
            )
        ).all()
    )
    attribute_value_count = (
        int(
            session.scalar(
                select(func.count(ProductAttributeRow.id)).where(
                    ProductAttributeRow.tenant_id == tenant_id,
                    ProductAttributeRow.attribute_definition_id.in_(
                        attribute_definition_ids
                    ),
                )
            )
            or 0
        )
        if attribute_definition_ids
        else 0
    )
    return affected_product_count, attribute_definition_ids, attribute_value_count


def get_category_delete_impact(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    category_id: UUID,
) -> CategoryDeleteImpactResponse:
    _require(permissions, "product.edit")
    category = repository.get_category(
        session,
        tenant_id=tenant_id,
        category_id=category_id,
    )
    if category is None:
        raise ApplicationError(
            "CATEGORY_NOT_FOUND",
            "分类不存在或已经被删除。",
            kind="not_found",
        )
    categories = _category_delete_scope(
        session,
        tenant_id=tenant_id,
        category=category,
    )
    affected_product_count, attribute_definition_ids, attribute_value_count = (
        _category_delete_counts(
            session,
            tenant_id=tenant_id,
            categories=categories,
        )
    )
    return CategoryDeleteImpactResponse(
        category_id=category.id,
        category_name=category.name,
        is_primary=category.parent_id is None,
        child_category_count=len(categories) - 1,
        affected_product_count=affected_product_count,
        attribute_definition_count=len(attribute_definition_ids),
        attribute_value_count=attribute_value_count,
    )


def delete_category(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    category_id: UUID,
    expected_version: int,
) -> CategoryDeleteResponse:
    _require(permissions, "product.edit")
    _lock_catalog_write(session, tenant_id=tenant_id)
    category = repository.get_category(
        session,
        tenant_id=tenant_id,
        category_id=category_id,
    )
    if category is None:
        raise ApplicationError(
            "CATEGORY_NOT_FOUND",
            "分类不存在或已经被删除。",
            kind="not_found",
        )
    if category.version != expected_version:
        raise ApplicationError(
            "CATEGORY_VERSION_CONFLICT",
            "分类已被其他人修改，请刷新后重试。",
            kind="conflict",
        )
    categories = _category_delete_scope(
        session,
        tenant_id=tenant_id,
        category=category,
    )
    category_ids = [row.id for row in categories]
    child_ids = [row.id for row in categories[1:]]
    affected_product_ids = list(
        session.scalars(
            select(ProductRow.id).where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.category_id.in_(category_ids),
            )
        ).all()
    )
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        product_ids=affected_product_ids,
    )
    affected_product_count, attribute_definition_ids, attribute_value_count = (
        _category_delete_counts(
            session,
            tenant_id=tenant_id,
            categories=categories,
        )
    )
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id
        )
    )
    roots = repository.list_sibling_categories(
        session,
        tenant_id=tenant_id,
        parent_id=None,
    )
    all_products_position = max(
        0,
        int(profile.all_products_position or 0) if profile else 0,
    )
    if category.parent_id is None:
        deleted_root_index = next(
            (index for index, root in enumerate(roots) if root.id == category.id),
            len(roots),
        )
        if deleted_root_index < all_products_position:
            all_products_position -= 1
        all_products_position = min(
            all_products_position,
            max(0, len(roots) - 1),
        )
        if profile is not None:
            profile.all_products_position = all_products_position
    else:
        all_products_position = min(all_products_position, len(roots))

    now = utcnow()
    before = {
        "category": _category_response(category).model_dump(mode="json"),
        "children": [
            _category_response(child).model_dump(mode="json")
            for child in categories[1:]
        ],
    }
    try:
        session.execute(
            update(ProductRow)
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.category_id.in_(category_ids),
            )
            .values(
                category_id=None,
                search_document_version=0,
                updated_at=now,
            )
        )
        if attribute_definition_ids:
            session.execute(
                update(ProductAttributeRow)
                .where(
                    ProductAttributeRow.tenant_id == tenant_id,
                    ProductAttributeRow.attribute_definition_id.in_(
                        attribute_definition_ids
                    ),
                )
                .values(attribute_definition_id=None, updated_at=now)
            )
            session.execute(
                delete(AttributeDefinitionRow).where(
                    AttributeDefinitionRow.tenant_id == tenant_id,
                    AttributeDefinitionRow.id.in_(attribute_definition_ids),
                )
            )
        if child_ids:
            session.execute(
                delete(ProductCategoryRow).where(
                    ProductCategoryRow.tenant_id == tenant_id,
                    ProductCategoryRow.id.in_(child_ids),
                )
            )
        session.execute(
            delete(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.id == category.id,
            )
        )
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=None,
                entity_type="CATEGORY",
                entity_id=str(category.id),
                action="category.deleted",
                before=before,
                after={
                    "deleted_category_count": len(categories),
                    "unclassified_product_count": affected_product_count,
                    "deleted_attribute_definition_count": len(
                        attribute_definition_ids
                    ),
                    "detached_attribute_value_count": attribute_value_count,
                },
                actor_membership_id=membership_id,
            )
        )
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "CATEGORY_DELETE_CONFLICT",
            "分类仍被其他数据引用，请刷新后重试。",
            kind="conflict",
        ) from exc
    _commit(
        session,
        conflict_code="CATEGORY_DELETE_CONFLICT",
        conflict_message="分类删除失败，请刷新后重试。",
    )
    return CategoryDeleteResponse(
        deleted_category_count=len(categories),
        unclassified_product_count=affected_product_count,
        deleted_attribute_definition_count=len(attribute_definition_ids),
        detached_attribute_value_count=attribute_value_count,
        all_products_position=all_products_position,
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
    _lock_catalog_write(session, tenant_id=tenant_id)
    source = repository.get_supplier_product(
        session, tenant_id=tenant_id, supplier_product_id=request.supplier_product_id
    )
    if source is None:
        raise ApplicationError("SUPPLIER_PRODUCT_NOT_FOUND", "Supplier product was not found.")
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        product_ids=[source.product_id],
    )
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
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_ids: list[UUID],
    commit: bool = True,
) -> dict[str, Any]:
    """Soft-delete SKUs while preserving inventory and quotation history."""
    _require(permissions, "product.edit")
    _lock_catalog_write(session, tenant_id=tenant_id)

    requested_ids = list(dict.fromkeys(sku_ids))
    rows = session.scalars(
        select(SkuRow)
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.id.in_(requested_ids),
        )
        .execution_options(include_deleted=True)
        .with_for_update()
    ).all()
    rows_by_id = {row.id: row for row in rows}
    selected_rows: list[SkuRow] = []
    failed_items: list[dict[str, Any]] = []
    for sku_id in requested_ids:
        row = rows_by_id.get(sku_id)
        if row is None or row.deleted_at is not None:
            failed_items.append(
                {
                    "sku_id": str(sku_id),
                    "reason": "SKU 不存在或已经删除",
                }
            )
            continue
        selected_rows.append(row)

    if not selected_rows:
        return {
            "success_count": 0,
            "failed_count": len(failed_items),
            "total_count": len(requested_ids),
            "failed_items": failed_items,
        }

    now = utcnow()
    selected_ids = [row.id for row in selected_rows]
    product_ids = list(dict.fromkeys(row.product_id for row in selected_rows))
    supplier_ids = {
        row.supplier_id for row in selected_rows if row.supplier_id is not None
    }
    offers = session.scalars(
        select(PublicCatalogOfferRow).where(
            PublicCatalogOfferRow.tenant_id == tenant_id,
            PublicCatalogOfferRow.sku_id.in_(selected_ids),
            PublicCatalogOfferRow.deleted_at.is_(None),
        )
    ).all()
    offers_by_sku = {row.sku_id: row for row in offers}

    for sku in selected_rows:
        before = {
            "sku_code": sku.sku_code,
            "status": sku.status,
            "version": sku.version,
        }
        sku.status = "ARCHIVED"
        sku.deleted_at = now
        sku.rollback_owner_batch_id = None
        sku.updated_at = now
        sku.updated_by_user_id = user_id
        sku.version += 1
        offer = offers_by_sku.get(sku.id)
        if offer is not None and offer.publication_status != "SUSPENDED":
            offer.publication_status = "SUSPENDED"
            offer.updated_at = now
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=sku.product_id,
                entity_type="SKU",
                entity_id=str(sku.id),
                action="sku.deleted",
                before=before,
                after={
                    "sku_code": sku.sku_code,
                    "status": sku.status,
                    "version": sku.version,
                    "deleted_at": now.isoformat(),
                },
                actor_membership_id=membership_id,
                occurred_at=now,
            )
        )

    session.flush()
    remaining_by_product = dict(
        session.execute(
            select(SkuRow.product_id, func.count(SkuRow.id))
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.product_id.in_(product_ids),
                SkuRow.deleted_at.is_(None),
                SkuRow.status != "ARCHIVED",
            )
            .group_by(SkuRow.product_id)
        ).all()
    )
    products = session.scalars(
        select(ProductRow).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id.in_(product_ids),
        )
    ).all()
    for product in products:
        product.current_version += 1
        product.search_document_version = 0
        product.updated_by = user_id
        product.updated_at = now
        if remaining_by_product.get(product.id, 0) == 0:
            product.status = "ARCHIVED"
            product.archived_at = now

    if supplier_ids:
        active_counts = dict(
            session.execute(
                select(SkuRow.supplier_id, func.count(SkuRow.id))
                .where(
                    SkuRow.tenant_id == tenant_id,
                    SkuRow.supplier_id.in_(supplier_ids),
                    SkuRow.status == "ACTIVE",
                    SkuRow.deleted_at.is_(None),
                )
                .group_by(SkuRow.supplier_id)
            ).all()
        )
        suppliers = session.scalars(
            select(SupplierRow).where(
                SupplierRow.tenant_id == tenant_id,
                SupplierRow.id.in_(supplier_ids),
                SupplierRow.deleted_at.is_(None),
            )
        ).all()
        for supplier in suppliers:
            supplier.active_skus = int(active_counts.get(supplier.id, 0))
            supplier.updated_at = now

    if commit:
        _commit(
            session,
            conflict_code="BATCH_DELETE_FAILED",
            conflict_message="批量删除失败，请刷新商品库后重试。",
        )
    else:
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ApplicationError(
                "BATCH_DELETE_FAILED",
                "批量删除失败，请刷新商品库后重试。",
                kind="conflict",
            ) from exc

    return {
        "success_count": len(selected_rows),
        "failed_count": len(failed_items),
        "total_count": len(requested_ids),
        "failed_items": failed_items,
    }


def _load_batch_sku_selection(
    session: Session,
    *,
    tenant_id: UUID,
    sku_ids: list[UUID],
) -> tuple[list[UUID], list[SkuRow], list[dict[str, Any]]]:
    """Load a de-duplicated, tenant-scoped SKU selection with stable failures."""

    requested_ids = list(dict.fromkeys(sku_ids))
    rows = session.scalars(
        select(SkuRow)
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.id.in_(requested_ids),
        )
        .execution_options(include_deleted=True)
    ).all()
    rows_by_id = {row.id: row for row in rows}
    selected_rows: list[SkuRow] = []
    failed_items: list[dict[str, Any]] = []
    for sku_id in requested_ids:
        row = rows_by_id.get(sku_id)
        if row is None or row.deleted_at is not None or row.status == "ARCHIVED":
            failed_items.append(
                {
                    "sku_id": str(sku_id),
                    "reason": "SKU 不存在、已删除或已经归档",
                }
            )
            continue
        selected_rows.append(row)
    return requested_ids, selected_rows, failed_items


def delete_all_products(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
) -> dict[str, int]:
    """Soft-delete one tenant's complete catalog with set-based updates."""

    _require(permissions, "product.edit")
    _lock_catalog_write(session, tenant_id=tenant_id)
    deleted_sku_count = int(
        session.scalar(
            select(func.count())
            .select_from(SkuRow)
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    deleted_product_count = int(
        session.scalar(
            select(func.count())
            .select_from(ProductRow)
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.deleted_at.is_(None),
                ProductRow.status != "ARCHIVED",
            )
        )
        or 0
    )
    if deleted_sku_count == 0 and deleted_product_count == 0:
        return {"deleted_product_count": 0, "deleted_sku_count": 0}

    now = utcnow()
    session.execute(
        update(PublicCatalogOfferRow)
        .where(
            PublicCatalogOfferRow.tenant_id == tenant_id,
            PublicCatalogOfferRow.deleted_at.is_(None),
            PublicCatalogOfferRow.publication_status != "SUSPENDED",
        )
        .values(publication_status="SUSPENDED", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    session.execute(
        update(SkuRow)
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.deleted_at.is_(None),
        )
        .values(
            status="ARCHIVED",
            deleted_at=now,
            rollback_owner_batch_id=None,
            updated_at=now,
            updated_by_user_id=user_id,
            version=SkuRow.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    session.execute(
        update(ProductRow)
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.deleted_at.is_(None),
            ProductRow.status != "ARCHIVED",
        )
        .values(
            status="ARCHIVED",
            archived_at=now,
            search_document_version=0,
            current_version=ProductRow.current_version + 1,
            updated_by=user_id,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    session.execute(
        update(SupplierRow)
        .where(
            SupplierRow.tenant_id == tenant_id,
            SupplierRow.deleted_at.is_(None),
            SupplierRow.active_skus != 0,
        )
        .values(active_skus=0, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="PRODUCT",
            entity_id=str(tenant_id),
            action="catalog.deleted_all",
            before={
                "product_count": deleted_product_count,
                "sku_count": deleted_sku_count,
            },
            after={"product_count": 0, "sku_count": 0},
            actor_membership_id=membership_id,
            occurred_at=now,
        )
    )
    _commit(
        session,
        conflict_code="DELETE_ALL_PRODUCTS_FAILED",
        conflict_message="全部商品删除失败，请刷新商品库后重试。",
    )
    return {
        "deleted_product_count": deleted_product_count,
        "deleted_sku_count": deleted_sku_count,
    }


def batch_update_sku_status(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_ids: list[UUID],
    status: str,
) -> dict[str, Any]:
    """Batch publish or unpublish SKUs with tenant isolation and audit history."""
    _require(permissions, "product.edit")
    _lock_catalog_write(session, tenant_id=tenant_id)

    if status not in SKU_STATUSES:
        raise ApplicationError(
            "INVALID_STATUS",
            f"Invalid status: {status}",
            kind="validation_failed",
        )

    requested_ids, selected_rows, failed_items = _load_batch_sku_selection(
        session,
        tenant_id=tenant_id,
        sku_ids=sku_ids,
    )
    if not selected_rows:
        return {
            "success_count": 0,
            "failed_count": len(failed_items),
            "total_count": len(requested_ids),
            "failed_items": failed_items,
            "affected_product_count": 0,
        }
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        sku_ids=[row.id for row in selected_rows],
    )

    now = utcnow()
    product_ids = list(dict.fromkeys(row.product_id for row in selected_rows))
    supplier_ids = {
        row.supplier_id for row in selected_rows if row.supplier_id is not None
    }
    for sku in selected_rows:
        previous_status = sku.status
        previous_version = sku.version
        sku.status = status
        sku.updated_at = now
        sku.updated_by_user_id = user_id
        sku.version += 1
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=sku.product_id,
                entity_type="SKU",
                entity_id=str(sku.id),
                action="sku.status_batch_updated",
                before={"status": previous_status, "version": previous_version},
                after={"status": status, "version": sku.version},
                actor_membership_id=membership_id,
                occurred_at=now,
            )
        )

    products = session.scalars(
        select(ProductRow).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id.in_(product_ids),
            ProductRow.deleted_at.is_(None),
        )
    ).all()
    for product in products:
        product.current_version += 1
        product.search_document_version = 0
        product.updated_by = user_id
        product.updated_at = now
        if status == "ACTIVE":
            product.status = "ACTIVE"
            product.archived_at = None

    session.flush()
    if supplier_ids:
        active_counts = dict(
            session.execute(
                select(SkuRow.supplier_id, func.count(SkuRow.id))
                .where(
                    SkuRow.tenant_id == tenant_id,
                    SkuRow.supplier_id.in_(supplier_ids),
                    SkuRow.status == "ACTIVE",
                    SkuRow.deleted_at.is_(None),
                )
                .group_by(SkuRow.supplier_id)
            ).all()
        )
        suppliers = session.scalars(
            select(SupplierRow).where(
                SupplierRow.tenant_id == tenant_id,
                SupplierRow.id.in_(supplier_ids),
                SupplierRow.deleted_at.is_(None),
            )
        ).all()
        for supplier in suppliers:
            supplier.active_skus = int(active_counts.get(supplier.id, 0))
            supplier.updated_at = now

    _commit(
        session,
        conflict_code="BATCH_UPDATE_FAILED",
        conflict_message="批量更新 SKU 状态失败，请刷新商品库后重试。",
    )

    return {
        "success_count": len(selected_rows),
        "failed_count": len(failed_items),
        "total_count": len(requested_ids),
        "failed_items": failed_items,
        "affected_product_count": len(products),
    }


def batch_update_sku_category(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_ids: list[UUID],
    category_id: UUID | None,
) -> dict[str, Any]:
    """Move the products represented by selected SKUs into one category."""

    _require(permissions, "product.edit")
    _lock_catalog_write(session, tenant_id=tenant_id)
    category = None
    if category_id is not None:
        category = session.scalar(
            select(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.id == category_id,
                ProductCategoryRow.deleted_at.is_(None),
                ProductCategoryRow.status != "ARCHIVED",
            )
        )
        if category is None:
            raise ApplicationError(
                "CATEGORY_NOT_FOUND",
                "分类不存在或已经归档。",
                kind="not_found",
            )

    requested_ids, selected_rows, failed_items = _load_batch_sku_selection(
        session,
        tenant_id=tenant_id,
        sku_ids=sku_ids,
    )
    product_ids = list(dict.fromkeys(row.product_id for row in selected_rows))
    products = session.scalars(
        select(ProductRow).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id.in_(product_ids),
            ProductRow.deleted_at.is_(None),
            ProductRow.status != "ARCHIVED",
        )
    ).all()
    products_by_id = {row.id: row for row in products}
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        product_ids=list(products_by_id),
    )
    valid_rows: list[SkuRow] = []
    for sku in selected_rows:
        if sku.product_id not in products_by_id:
            failed_items.append(
                {"sku_id": str(sku.id), "reason": "所属商品不存在或已经归档"}
            )
        else:
            valid_rows.append(sku)

    now = utcnow()
    for product in products:
        previous_category_id = product.category_id
        product.category_id = category_id
        product.current_version += 1
        product.search_document_version = 0
        product.updated_by = user_id
        product.updated_at = now
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product.id,
                entity_type="PRODUCT",
                entity_id=str(product.id),
                action="product.category_batch_updated",
                before={
                    "category_id": str(previous_category_id)
                    if previous_category_id
                    else None
                },
                after={"category_id": str(category_id) if category_id else None},
                actor_membership_id=membership_id,
                occurred_at=now,
            )
        )

    if products:
        _commit(
            session,
            conflict_code="BATCH_CATEGORY_UPDATE_FAILED",
            conflict_message="批量修改分类失败，请刷新商品库后重试。",
        )
    return {
        "success_count": len(valid_rows),
        "failed_count": len(failed_items),
        "total_count": len(requested_ids),
        "failed_items": failed_items,
        "affected_product_count": len(products),
    }


def batch_update_sku_pinned(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    sku_ids: list[UUID],
    pinned: bool,
) -> dict[str, Any]:
    """Pin or unpin the products represented by selected SKUs."""

    _require(permissions, "product.edit")
    _lock_catalog_write(session, tenant_id=tenant_id)
    requested_ids, selected_rows, failed_items = _load_batch_sku_selection(
        session,
        tenant_id=tenant_id,
        sku_ids=sku_ids,
    )
    product_ids = list(dict.fromkeys(row.product_id for row in selected_rows))
    products = session.scalars(
        select(ProductRow).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id.in_(product_ids),
            ProductRow.deleted_at.is_(None),
            ProductRow.status != "ARCHIVED",
        )
    ).all()
    products_by_id = {row.id: row for row in products}
    _release_rollback_ownership(
        session,
        tenant_id=tenant_id,
        product_ids=list(products_by_id),
    )
    valid_rows: list[SkuRow] = []
    for sku in selected_rows:
        if sku.product_id not in products_by_id:
            failed_items.append(
                {"sku_id": str(sku.id), "reason": "所属商品不存在或已经归档"}
            )
        else:
            valid_rows.append(sku)

    now = utcnow()
    for product in products:
        was_pinned = product.storefront_pinned_at is not None
        product.storefront_pinned_at = now if pinned else None
        product.current_version += 1
        product.updated_by = user_id
        product.updated_at = now
        session.add(
            ProductAuditEventRow(
                tenant_id=tenant_id,
                product_id=product.id,
                entity_type="PRODUCT",
                entity_id=str(product.id),
                action="product.storefront_pin_updated",
                before={"pinned": was_pinned},
                after={"pinned": pinned},
                actor_membership_id=membership_id,
                occurred_at=now,
            )
        )

    if products:
        _commit(
            session,
            conflict_code="BATCH_PIN_UPDATE_FAILED",
            conflict_message="批量置顶失败，请刷新商品库后重试。",
        )
    return {
        "success_count": len(valid_rows),
        "failed_count": len(failed_items),
        "total_count": len(requested_ids),
        "failed_items": failed_items,
        "affected_product_count": len(products),
    }
