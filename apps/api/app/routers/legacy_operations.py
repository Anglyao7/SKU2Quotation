from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..models import (
    FileDetectionResponse,
    ImportJob,
    PriceCalculationRequest,
    PriceCalculationResponse,
    Product,
    ReviewApprovalResponse,
    ReviewItem,
    ReviewItemUpdate,
    Supplier,
    SupplierFileImportResponse,
)
from ..services.auth.dependencies import (
    RequestContext,
    current_context,
    get_authenticated_session,
    require_request_context,
)
from ..use_cases import legacy_operations as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["legacy-operations"])


@router.get("/suppliers", response_model=list[Supplier])
def list_suppliers(
    session: Session = Depends(get_authenticated_session),
) -> list[Supplier]:
    context = current_context(session)
    try:
        return use_cases.list_suppliers(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/imports", response_model=list[ImportJob])
def list_imports(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_authenticated_session),
) -> list[ImportJob]:
    context = current_context(session)
    try:
        return use_cases.list_imports(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/imports/{job_id}", response_model=ImportJob)
def get_import(
    job_id: str,
    session: Session = Depends(get_authenticated_session),
) -> ImportJob:
    context = current_context(session)
    try:
        return use_cases.get_import(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/imports/detect", response_model=FileDetectionResponse)
async def detect_upload(
    file: UploadFile = File(...),
    context: RequestContext = Depends(require_request_context),
) -> FileDetectionResponse:
    if "product.import" not in context.permissions:
        raise application_http_error(
            ApplicationError(
                "PERMISSION_DENIED",
                "Permission is required: product.import",
                kind="forbidden",
            )
        )
    header = await file.read(32)
    await file.close()
    return use_cases.detect_upload(file.filename or "unnamed", header)


@router.post(
    "/imports",
    response_model=SupplierFileImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_import(
    file: UploadFile = File(...),
    supplier_id: str | None = Form(default=None),
    source_type: str = Form(default="UNKNOWN"),
    session: Session = Depends(get_authenticated_session),
) -> SupplierFileImportResponse:
    context = current_context(session)
    try:
        return await use_cases.create_import(
            session,
            upload=file,
            supplier_id=supplier_id,
            source_type=source_type,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/review-items", response_model=list[ReviewItem])
def list_review_items(
    job_id: str | None = None,
    review_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_authenticated_session),
) -> list[ReviewItem]:
    context = current_context(session)
    try:
        return use_cases.list_review_items(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            job_id=job_id,
            review_status=review_status,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/review-items/{item_id}", response_model=ReviewItem)
def update_review_item(
    item_id: str,
    request: ReviewItemUpdate,
    session: Session = Depends(get_authenticated_session),
) -> ReviewItem:
    context = current_context(session)
    try:
        return use_cases.update_review_item(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            item_id=item_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/review-items/{item_id}/approve", response_model=ReviewApprovalResponse)
def approve_review_item(
    item_id: str,
    session: Session = Depends(get_authenticated_session),
) -> ReviewApprovalResponse:
    context = current_context(session)
    try:
        return use_cases.approve_review_item(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            item_id=item_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/pricing/calculate", response_model=PriceCalculationResponse)
def pricing_calculation(
    request: PriceCalculationRequest,
    _context: RequestContext = Depends(require_request_context),
) -> PriceCalculationResponse:
    return use_cases.calculate_pricing(request)
