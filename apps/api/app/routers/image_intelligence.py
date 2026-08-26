from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..image_intelligence_schemas import (
    ImageEmbeddingSettingsResponse,
    ImageEmbeddingSettingsUpdateRequest,
    ImageIndexJobResponse,
    ImageIndexJobResumeRequest,
    ImageIndexJobStartRequest,
    ImageIndexStatusResponse,
    ImageProjectionResponse,
    ImageSearchResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import image_intelligence as use_cases
from ..use_cases import embedding_management
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["image-intelligence"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get(
    "/ai/image-embedding/settings",
    response_model=ImageEmbeddingSettingsResponse,
)
def get_image_embedding_settings(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEmbeddingSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return embedding_management.get_image_embedding_settings(
            session,
            context=current_context(session),
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/ai/image-embedding/settings",
    response_model=ImageEmbeddingSettingsResponse,
)
def update_image_embedding_settings(
    payload: ImageEmbeddingSettingsUpdateRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEmbeddingSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return embedding_management.update_image_embedding_settings(
            session,
            context=current_context(session),
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/ai/image-search/index",
    response_model=ImageIndexStatusResponse,
)
def get_image_index_status(
    session: Session = Depends(get_authenticated_session),
) -> ImageIndexStatusResponse:
    context = current_context(session)
    try:
        return use_cases.get_image_index_status(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/ai/image-search/index/jobs",
    response_model=ImageIndexJobResponse,
    status_code=202,
)
def start_image_index_job(
    payload: ImageIndexJobStartRequest,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> ImageIndexJobResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-image-index-jobs",
        limit=configured_limit("RATE_LIMIT_AI_IMAGE_INDEX_UPDATES", 12),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_IMAGE_INDEX_UPDATE_WINDOW_SECONDS",
            3600,
            maximum=86_400,
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.start_image_index_job(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/ai/image-search/index/jobs/latest",
    response_model=ImageIndexJobResponse | None,
)
def latest_image_index_job(
    session: Session = Depends(get_authenticated_session),
) -> ImageIndexJobResponse | None:
    context = current_context(session)
    try:
        return use_cases.latest_image_index_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/ai/image-search/index/jobs/{job_id}",
    response_model=ImageIndexJobResponse,
)
def get_image_index_job(
    job_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> ImageIndexJobResponse:
    context = current_context(session)
    try:
        return use_cases.get_image_index_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/ai/image-search/index/jobs/{job_id}/pause",
    response_model=ImageIndexJobResponse,
)
def pause_image_index_job(
    job_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> ImageIndexJobResponse:
    try:
        return use_cases.pause_image_index_job(
            session,
            context=current_context(session),
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/ai/image-search/index/jobs/{job_id}/resume",
    response_model=ImageIndexJobResponse,
)
def resume_image_index_job(
    job_id: UUID,
    payload: ImageIndexJobResumeRequest | None = None,
    session: Session = Depends(get_authenticated_session),
) -> ImageIndexJobResponse:
    try:
        return use_cases.resume_image_index_job(
            session,
            context=current_context(session),
            job_id=job_id,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/product-images/{image_id}/intelligence", response_model=ImageProjectionResponse)
def project_product_image(
    image_id: UUID,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> ImageProjectionResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-image-project",
        limit=configured_limit("RATE_LIMIT_AI_IMAGE_PROJECT_REQUESTS", 20),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_IMAGE_PROJECT_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.project_product_image(session, tenant_id=context.tenant_id, permissions=context.permissions, image_id=image_id)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc

@router.post("/image-searches", response_model=ImageSearchResponse)
def image_search(
    request: Request,
    file: UploadFile = File(...),
    limit: int = Query(default=10, ge=1, le=25),
    session: Session = Depends(get_authenticated_session),
) -> ImageSearchResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-image-search",
        limit=configured_limit("RATE_LIMIT_AI_IMAGE_SEARCH_REQUESTS", 10),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_IMAGE_SEARCH_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    content = file.file.read(int(__import__("os").getenv("IMAGE_SEARCH_MAX_BYTES", str(20 * 1024 * 1024))) + 1)
    file.file.close()
    try:
        return use_cases.search_by_image(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, filename=file.filename or "query.img", declared_content_type=file.content_type or "application/octet-stream", content=content, limit=limit)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
