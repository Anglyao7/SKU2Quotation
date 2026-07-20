from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..product_center_schemas import (
    AttributeDefinitionCreateRequest,
    AttributeDefinitionResponse,
    CategoryCreateRequest,
    CategoryResponse,
    ProductCard,
    ProductDetail,
    ProductReviewQueueItem,
    PublicCatalogOfferResponse,
    PublicCatalogOfferUpsertRequest,
    SkuBatchCreateRequest,
    SkuResponse,
    SkuUpdateRequest,
    SupplierPriceCreateRequest,
    SupplierPriceResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import product_center as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["product-center"])


def _context(session: Session):
    return current_context(session)


@router.get("/products", response_model=list[ProductCard])
def list_products(
    q: str = Query(default="", max_length=200),
    category_id: UUID | None = None,
    supplier_id: str | None = Query(default=None, max_length=40),
    product_status: list[str] = Query(default=[], alias="status"),
    approved_images_only: bool = False,
    limit: int = Query(default=24, ge=1, le=100),
    session: Session = Depends(get_authenticated_session),
) -> list[ProductCard]:
    context = _context(session)
    try:
        return use_cases.list_products(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            query=q,
            category_id=category_id,
            supplier_id=supplier_id,
            statuses=product_status,
            approved_images_only=approved_images_only,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/products/{product_id}", response_model=ProductDetail)
def get_product(
    product_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> ProductDetail:
    context = _context(session)
    try:
        return use_cases.get_product(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/products/{product_id}/skus",
    response_model=list[SkuResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_skus(
    product_id: UUID,
    request: SkuBatchCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> list[SkuResponse]:
    context = _context(session)
    try:
        return use_cases.create_skus(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            product_id=product_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/skus/{sku_id}", response_model=SkuResponse)
def update_sku(
    sku_id: UUID,
    request: SkuUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> SkuResponse:
    context = _context(session)
    try:
        return use_cases.update_sku(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            sku_id=sku_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/products/{product_id}/public-offers",
    response_model=list[PublicCatalogOfferResponse],
)
def list_public_offers(
    product_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> list[PublicCatalogOfferResponse]:
    context = _context(session)
    try:
        return use_cases.list_public_offers(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/skus/{sku_id}/public-offer",
    response_model=PublicCatalogOfferResponse,
)
def upsert_public_offer(
    sku_id: UUID,
    request: PublicCatalogOfferUpsertRequest,
    session: Session = Depends(get_authenticated_session),
) -> PublicCatalogOfferResponse:
    context = _context(session)
    try:
        return use_cases.upsert_public_offer(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            sku_id=sku_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(
    session: Session = Depends(get_authenticated_session),
) -> list[CategoryResponse]:
    context = _context(session)
    try:
        return use_cases.list_categories(
            session, tenant_id=context.tenant_id, permissions=context.permissions
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED
)
def create_category(
    request: CategoryCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> CategoryResponse:
    context = _context(session)
    try:
        return use_cases.create_category(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/attribute-definitions", response_model=list[AttributeDefinitionResponse])
def list_attribute_definitions(
    category_id: UUID | None = None,
    session: Session = Depends(get_authenticated_session),
) -> list[AttributeDefinitionResponse]:
    context = _context(session)
    try:
        return use_cases.list_attribute_definitions(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            category_id=category_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/attribute-definitions",
    response_model=AttributeDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_attribute_definition(
    request: AttributeDefinitionCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> AttributeDefinitionResponse:
    context = _context(session)
    try:
        return use_cases.create_attribute_definition(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/products/{product_id}/prices", response_model=list[SupplierPriceResponse])
def list_prices(
    product_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> list[SupplierPriceResponse]:
    context = _context(session)
    try:
        return use_cases.list_prices(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/product-prices",
    response_model=SupplierPriceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_price(
    request: SupplierPriceCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> SupplierPriceResponse:
    context = _context(session)
    try:
        return use_cases.create_price(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/product-review-items", response_model=list[ProductReviewQueueItem])
def list_product_review_items(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_authenticated_session),
) -> list[ProductReviewQueueItem]:
    context = _context(session)
    try:
        return use_cases.list_review_queue(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
