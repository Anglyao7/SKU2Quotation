from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..catalog_translation_schemas import (
    CatalogTranslationBatchPageResponse,
    CatalogTranslationBatchResponse,
    CatalogTranslationJobResponse,
    CatalogTranslationProductRetryRequest,
    CatalogTranslationProductUpdateRequest,
    CatalogTranslationProductDetail,
    CatalogTranslationProductListResponse,
    CatalogLanguagePackPublishRequest,
    CatalogLanguagePackResponse,
    CatalogTranslationJobStartRequest,
    CatalogTranslationStatusResponse,
)
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import catalog_translations as use_cases
from .errors import application_http_error


router = APIRouter(
    prefix="/api/v1/catalog/translations",
    tags=["catalog-translations"],
)


@router.get("/status", response_model=CatalogTranslationStatusResponse)
def get_translation_status(
    target_locale: str = Query(default="en-US", max_length=20),
    include_latest_job: bool = Query(
        default=True,
        description=(
            "Include the latest job in the coverage response. Clients may "
            "load /jobs/latest in parallel for a faster history-first UI."
        ),
    ),
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationStatusResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.get_translation_status(
                session,
                tenant_id=scoped_context.tenant_id,
                permissions=scoped_context.permissions,
                target_locale=target_locale,
                include_latest_job=include_latest_job,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs",
    response_model=CatalogTranslationJobResponse,
    status_code=202,
)
def start_translation_job(
    payload: CatalogTranslationJobStartRequest,
    request: Request,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, requester_membership_id):
            enforce_rate_limit(
                request,
                scope="catalog-translation-jobs",
                limit=configured_limit(
                    "RATE_LIMIT_CATALOG_TRANSLATION_JOBS",
                    12,
                ),
                window_seconds=configured_limit(
                    "RATE_LIMIT_CATALOG_TRANSLATION_JOB_WINDOW_SECONDS",
                    3_600,
                    maximum=86_400,
                ),
                token=request.headers.get("authorization"),
            )
            return use_cases.start_translation_job(
                session,
                context=scoped_context,
                request=payload,
                requested_by_membership_id=requester_membership_id,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/jobs/latest",
    response_model=CatalogTranslationJobResponse | None,
)
def latest_translation_job(
    target_locale: str = Query(default="en-US", max_length=20),
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse | None:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.latest_translation_job(
                session,
                tenant_id=scoped_context.tenant_id,
                permissions=scoped_context.permissions,
                target_locale=target_locale,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/jobs/{job_id}",
    response_model=CatalogTranslationJobResponse,
)
def get_translation_job(
    job_id: UUID,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.get_translation_job(
                session,
                tenant_id=scoped_context.tenant_id,
                permissions=scoped_context.permissions,
                job_id=job_id,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/jobs/{job_id}/batch-history",
    response_model=CatalogTranslationBatchPageResponse,
)
def list_translation_batch_history(
    job_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    status: str = Query(default="ALL", max_length=30),
    include_skus: bool = Query(default=False),
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationBatchPageResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.list_translation_batch_page(
                session,
                tenant_id=scoped_context.tenant_id,
                permissions=scoped_context.permissions,
                job_id=job_id,
                page=page,
                page_size=page_size,
                status_filter=status,
                include_skus=include_skus,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/jobs/{job_id}/batches",
    response_model=list[CatalogTranslationBatchResponse],
)
def list_translation_batches(
    job_id: UUID,
    include_skus: bool = Query(
        default=True,
        description=(
            "Include every SKU ID and reference. Set false for lightweight "
            "polling; the response keeps a three-SKU preview."
        ),
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=500,
        description="Return only the newest logical batches.",
    ),
    include_failed: bool = Query(
        default=True,
        description="Keep older failed batches when a newest-batch limit is used.",
    ),
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> list[CatalogTranslationBatchResponse]:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.list_translation_batches(
                session,
                tenant_id=scoped_context.tenant_id,
                permissions=scoped_context.permissions,
                job_id=job_id,
                include_skus=include_skus,
                limit=limit,
                include_failed=include_failed,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs/{job_id}/batches/{batch_id}/retry",
    response_model=CatalogTranslationJobResponse,
    status_code=202,
)
def retry_translation_batch(
    job_id: UUID,
    batch_id: UUID,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, requester_membership_id):
            return use_cases.retry_translation_batch(
                session,
                context=scoped_context,
                job_id=job_id,
                batch_id=batch_id,
                requested_by_membership_id=requester_membership_id,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/products/{product_id}/retry",
    response_model=CatalogTranslationJobResponse,
    status_code=202,
)
def retry_translation_product(
    product_id: UUID,
    payload: CatalogTranslationProductRetryRequest,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, requester_membership_id):
            return use_cases.retry_translation_product(
                session,
                context=scoped_context,
                product_id=product_id,
                request=payload,
                requested_by_membership_id=requester_membership_id,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/products",
    response_model=CatalogTranslationProductListResponse,
)
def list_translation_products(
    target_locale: str = Query(default="en-US", max_length=20),
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationProductListResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.list_translation_products(
                session,
                context=scoped_context,
                target_locale=target_locale,
                query=q,
                page=page,
                page_size=page_size,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/products/{product_id}",
    response_model=CatalogTranslationProductDetail,
)
def get_translation_product(
    product_id: UUID,
    target_locale: str = Query(default="en-US", max_length=20),
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationProductDetail:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.get_translation_product(
                session,
                context=scoped_context,
                product_id=product_id,
                target_locale=target_locale,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/products/{product_id}/translation",
    response_model=CatalogTranslationProductDetail,
)
def update_translation_product(
    product_id: UUID,
    payload: CatalogTranslationProductUpdateRequest,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationProductDetail:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.update_translation_product(
                session,
                context=scoped_context,
                product_id=product_id,
                request=payload,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/language-pack/publish",
    response_model=CatalogLanguagePackResponse,
)
def publish_reviewed_language_pack(
    payload: CatalogLanguagePackPublishRequest,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogLanguagePackResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.publish_reviewed_language_pack(
                session,
                context=scoped_context,
                request=payload,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs/{job_id}/pause",
    response_model=CatalogTranslationJobResponse,
)
def pause_translation_job(
    job_id: UUID,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.pause_translation_job(
                session,
                context=scoped_context,
                job_id=job_id,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs/{job_id}/resume",
    response_model=CatalogTranslationJobResponse,
)
def resume_translation_job(
    job_id: UUID,
    tenant_id: UUID | None = Query(default=None),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        with use_cases.platform_admin_translation_scope(
            session,
            context=context,
            tenant_id=tenant_id,
        ) as (scoped_context, _requester_membership_id):
            return use_cases.resume_translation_job(
                session,
                context=scoped_context,
                job_id=job_id,
            )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
