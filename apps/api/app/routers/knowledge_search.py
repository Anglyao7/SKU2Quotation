from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..knowledge_embedding_schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeProjectionResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import knowledge_search as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/ai", tags=["knowledge-search"])


@router.post(
    "/knowledge/products/{product_id}/project",
    response_model=KnowledgeProjectionResponse,
)
def project_product(
    product_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> KnowledgeProjectionResponse:
    try:
        return use_cases.project_product(
            session,
            tenant_id=current_context(session).tenant_id,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/search/products", response_model=HybridSearchResponse)
def search_products(
    request: HybridSearchRequest,
    session: Session = Depends(get_authenticated_session),
) -> HybridSearchResponse:
    try:
        return use_cases.search_products(
            session,
            tenant_id=current_context(session).tenant_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
