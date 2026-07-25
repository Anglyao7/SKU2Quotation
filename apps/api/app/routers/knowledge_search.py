from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..knowledge_embedding_schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeProjectionResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import knowledge_search as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/ai", tags=["knowledge-search"])


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
