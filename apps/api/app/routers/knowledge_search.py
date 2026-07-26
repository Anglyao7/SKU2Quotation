from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..knowledge_embedding_schemas import (
    EmbeddingSettingsResponse,
    EmbeddingSettingsUpdateRequest,
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeIndexJobResponse,
    KnowledgeIndexJobStartRequest,
    KnowledgeIndexRebuildRequest,
    KnowledgeIndexStatusResponse,
    KnowledgeIndexUpdateResponse,
    KnowledgeProjectionResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import embedding_management
from ..use_cases import knowledge_search as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/ai", tags=["knowledge-search"])


@router.get(
    "/embedding/settings",
    response_model=EmbeddingSettingsResponse,
)
def get_embedding_settings(
    session: Session = Depends(get_authenticated_session),
) -> EmbeddingSettingsResponse:
    context = current_context(session)
    try:
        return embedding_management.get_settings(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/embedding/settings",
    response_model=EmbeddingSettingsResponse,
)
def update_embedding_settings(
    payload: EmbeddingSettingsUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> EmbeddingSettingsResponse:
    context = current_context(session)
    try:
        return embedding_management.update_settings(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/knowledge/index",
    response_model=KnowledgeIndexStatusResponse,
)
def get_index_status(
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeIndexStatusResponse:
    context = current_context(session)
    try:
        return use_cases.get_index_status(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/knowledge/index/jobs",
    response_model=KnowledgeIndexJobResponse,
    status_code=202,
)
def start_index_job(
    payload: KnowledgeIndexJobStartRequest,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeIndexJobResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-knowledge-index-jobs",
        limit=configured_limit("RATE_LIMIT_AI_INDEX_UPDATES", 12),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_INDEX_UPDATE_WINDOW_SECONDS", 3600, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.start_index_job(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/knowledge/index/jobs/latest",
    response_model=KnowledgeIndexJobResponse | None,
)
def latest_index_job(
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeIndexJobResponse | None:
    context = current_context(session)
    try:
        return use_cases.latest_index_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/knowledge/index/jobs/{job_id}",
    response_model=KnowledgeIndexJobResponse,
)
def get_index_job(
    job_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeIndexJobResponse:
    context = current_context(session)
    try:
        return use_cases.get_index_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/knowledge/index/update",
    response_model=KnowledgeIndexUpdateResponse,
)
def update_index(
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeIndexUpdateResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-knowledge-index-update",
        limit=configured_limit("RATE_LIMIT_AI_INDEX_UPDATES", 12),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_INDEX_UPDATE_WINDOW_SECONDS", 3600, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.update_index(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            full_rebuild=False,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/knowledge/index/rebuild",
    response_model=KnowledgeIndexUpdateResponse,
)
def rebuild_index(
    payload: KnowledgeIndexRebuildRequest,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeIndexUpdateResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-knowledge-index-rebuild",
        limit=configured_limit("RATE_LIMIT_AI_INDEX_REBUILDS", 3),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_INDEX_REBUILD_WINDOW_SECONDS", 86_400, maximum=604_800
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.update_index(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            full_rebuild=payload.confirm_full_rebuild,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/knowledge/products/{product_id}/project",
    response_model=KnowledgeProjectionResponse,
)
def project_product(
    product_id: UUID,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeProjectionResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-knowledge-project",
        limit=configured_limit("RATE_LIMIT_AI_PROJECT_REQUESTS", 20),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_PROJECT_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.project_product(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/search/products", response_model=HybridSearchResponse)
def search_products(
    payload: HybridSearchRequest,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> HybridSearchResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-product-search",
        limit=configured_limit("RATE_LIMIT_AI_SEARCH_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_SEARCH_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.search_products(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
