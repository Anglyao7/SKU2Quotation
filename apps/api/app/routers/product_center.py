from __future__ import annotations

from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..domain.errors import ApplicationError
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
    ProductCard,
    ProductDeleteAllJobResponse,
    ProductDeleteAllRequest,
    ProductDetail,
    ProductReviewQueueItem,
    PublicCatalogOfferResponse,
    PublicCatalogOfferUpsertRequest,
    SkuBatchCreateRequest,
    SkuBatchDeleteRequest,
    SkuBatchUpdateCategoryRequest,
    SkuBatchUpdatePinnedRequest,
    SkuBatchUpdateStatusRequest,
    SkuBatchOperationResponse,
    SkuListPage,
    SkuResponse,
    SkuUpdateRequest,
    SupplierPriceCreateRequest,
    SupplierPriceResponse,
)
from ..database import get_auth_session
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.auth.service import AuthError, verify_current_user_password
from ..services.category_template_import import (
    CATEGORY_TEMPLATE_MAX_FILE_BYTES,
    CATEGORY_TEMPLATE_PATH,
    CategoryTemplateValidationError,
    parse_category_template,
)
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import product_center as use_cases
from ..use_cases import catalog_deletion
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["product-center"])


def _context(session: Session):
    return current_context(session)


@router.get("/category-template.xlsx")
def download_category_template() -> Response:
    filename = "分类模板.xlsx"
    if not CATEGORY_TEMPLATE_PATH.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "CATEGORY_TEMPLATE_UNAVAILABLE",
                "message": "分类模板暂时不可用，请稍后重试。",
            },
        )
    return Response(
        content=CATEGORY_TEMPLATE_PATH.read_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                'attachment; filename="category-template.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "public, max-age=300",
        },
    )


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

@router.get("/product-center/skus", response_model=SkuListPage)
def list_skus(
    q: str = Query(default="", max_length=200),
    category_id: UUID | None = None,
    sku_status: list[str] = Query(default=[], alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_supplier_summary: bool = Query(default=True),
    session: Session = Depends(get_authenticated_session),
) -> SkuListPage:
    context = _context(session)
    try:
        return use_cases.list_skus(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            query=q,
            category_id=category_id,
            statuses=sku_status,
            page=page,
            page_size=page_size,
            include_supplier_summary=include_supplier_summary,
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


@router.post("/categories/import", response_model=CategoryImportResponse)
async def import_categories(
    file: UploadFile = File(...),
    session: Session = Depends(get_authenticated_session),
) -> CategoryImportResponse:
    context = _context(session)
    if "product.edit" not in context.permissions:
        await file.close()
        raise application_http_error(
            ApplicationError(
                "PERMISSION_REQUIRED",
                "Permission required: product.edit",
                kind="forbidden",
            )
        )
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CATEGORY_TEMPLATE_FILE_TYPE_INVALID",
                "message": "分类导入只支持 .xlsx 文件，请下载分类模板后填写。",
            },
        )
    try:
        content = await file.read(CATEGORY_TEMPLATE_MAX_FILE_BYTES + 1)
    finally:
        await file.close()
    if len(content) > CATEGORY_TEMPLATE_MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "CATEGORY_TEMPLATE_TOO_LARGE",
                "message": "分类模板超过 50 MB，请拆分后分别导入。",
            },
        )
    try:
        parsed = await run_in_threadpool(parse_category_template, content)
    except CategoryTemplateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CATEGORY_TEMPLATE_INVALID",
                "message": str(exc),
                "issues": [issue.as_dict() for issue in exc.issues],
            },
        ) from exc

    try:
        return use_cases.import_categories(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            parsed=parsed,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/categories/layout", response_model=CategoryLayoutResponse)
def get_category_layout(
    session: Session = Depends(get_authenticated_session),
) -> CategoryLayoutResponse:
    context = _context(session)
    try:
        return use_cases.get_category_layout(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/categories/layout", response_model=CategoryLayoutResponse)
def update_category_layout(
    request: CategoryLayoutUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> CategoryLayoutResponse:
    context = _context(session)
    try:
        return use_cases.update_category_layout(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/categories/reorder", response_model=list[CategoryResponse])
def reorder_categories(
    request: CategoryReorderRequest,
    session: Session = Depends(get_authenticated_session),
) -> list[CategoryResponse]:
    context = _context(session)
    try:
        return use_cases.reorder_categories(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: UUID,
    request: CategoryUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> CategoryResponse:
    context = _context(session)
    try:
        return use_cases.update_category(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            category_id=category_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/categories/{category_id}/delete-impact",
    response_model=CategoryDeleteImpactResponse,
)
def get_category_delete_impact(
    category_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> CategoryDeleteImpactResponse:
    context = _context(session)
    try:
        return use_cases.get_category_delete_impact(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            category_id=category_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/categories/{category_id}",
    response_model=CategoryDeleteResponse,
)
def delete_category(
    category_id: UUID,
    expected_version: int = Query(ge=1),
    session: Session = Depends(get_authenticated_session),
) -> CategoryDeleteResponse:
    context = _context(session)
    try:
        return use_cases.delete_category(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            category_id=category_id,
            expected_version=expected_version,
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


@router.post("/skus/batch-delete", response_model=SkuBatchOperationResponse, status_code=status.HTTP_200_OK)
def batch_delete_skus(
    request: SkuBatchDeleteRequest,
    session: Session = Depends(get_authenticated_session),
) -> SkuBatchOperationResponse:
    """批量删除 SKU"""
    context = _context(session)
    try:
        result = use_cases.batch_delete_skus(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            sku_ids=request.sku_ids,
        )
        return SkuBatchOperationResponse(**result)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/product-center/products/delete-all",
    response_model=ProductDeleteAllJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_all_products(
    payload: ProductDeleteAllRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_authenticated_session),
    auth_session: Session = Depends(get_auth_session),
) -> ProductDeleteAllJobResponse:
    """Verify the password and enqueue deletion without holding the HTTP request."""

    context = _context(session)
    response.headers["Cache-Control"] = "no-store"
    enforce_rate_limit(
        request,
        scope="product-delete-all",
        limit=configured_limit("RATE_LIMIT_DELETE_ALL_PRODUCTS_REQUESTS", 5),
        window_seconds=configured_limit(
            "RATE_LIMIT_DELETE_ALL_PRODUCTS_WINDOW_SECONDS",
            300,
            maximum=86_400,
        ),
        additional_subjects=(("user", str(context.user_id)),),
    )
    try:
        verify_current_user_password(
            auth_session,
            user_id=context.user_id,
            password=payload.password.get_secret_value(),
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": exc.code,
                "message": "密码错误，请重新输入。",
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    try:
        return catalog_deletion.start_catalog_delete_job(
            session,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/product-center/products/delete-all/{job_id}",
    response_model=ProductDeleteAllJobResponse,
)
def get_delete_all_products_job(
    job_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ProductDeleteAllJobResponse:
    """Return progress for an asynchronous complete-catalog deletion."""

    context = _context(session)
    response.headers["Cache-Control"] = "no-store"
    try:
        return catalog_deletion.get_catalog_delete_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/skus/batch-update-status", response_model=SkuBatchOperationResponse, status_code=status.HTTP_200_OK)
def batch_update_sku_status(
    request: SkuBatchUpdateStatusRequest,
    session: Session = Depends(get_authenticated_session),
) -> SkuBatchOperationResponse:
    """批量更新 SKU 状态"""
    context = _context(session)
    try:
        result = use_cases.batch_update_sku_status(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            sku_ids=request.sku_ids,
            status=request.status,
        )
        return SkuBatchOperationResponse(**result)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/skus/batch-update-category",
    response_model=SkuBatchOperationResponse,
    status_code=status.HTTP_200_OK,
)
def batch_update_sku_category(
    request: SkuBatchUpdateCategoryRequest,
    session: Session = Depends(get_authenticated_session),
) -> SkuBatchOperationResponse:
    """批量修改所选 SKU 对应商品的分类。"""

    context = _context(session)
    try:
        result = use_cases.batch_update_sku_category(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            sku_ids=request.sku_ids,
            category_id=request.category_id,
        )
        return SkuBatchOperationResponse(**result)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/skus/batch-update-pinned",
    response_model=SkuBatchOperationResponse,
    status_code=status.HTTP_200_OK,
)
def batch_update_sku_pinned(
    request: SkuBatchUpdatePinnedRequest,
    session: Session = Depends(get_authenticated_session),
) -> SkuBatchOperationResponse:
    """批量置顶或取消置顶所选 SKU 对应的商品。"""

    context = _context(session)
    try:
        result = use_cases.batch_update_sku_pinned(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            sku_ids=request.sku_ids,
            pinned=request.pinned,
        )
        return SkuBatchOperationResponse(**result)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
