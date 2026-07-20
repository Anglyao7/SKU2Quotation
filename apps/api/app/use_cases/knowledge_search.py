from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..knowledge_embedding_schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeProjectionResponse,
)
from ..services.hybrid_search import hybrid_product_search
from ..services.knowledge import KnowledgeProjectionError, project_product_knowledge


def project_product(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
) -> KnowledgeProjectionResponse:
    try:
        result = project_product_knowledge(
            session,
            tenant_id=tenant_id,
            product_id=product_id,
        )
        session.commit()
    except KnowledgeProjectionError as exc:
        session.rollback()
        raise ApplicationError("PRODUCT_NOT_FOUND", str(exc), kind="not_found") from exc
    except ValueError as exc:
        session.rollback()
        raise ApplicationError("KNOWLEDGE_PROJECTION_INVALID", str(exc)) from exc
    return KnowledgeProjectionResponse(**asdict(result))


def search_products(
    session: Session,
    *,
    tenant_id: UUID,
    request: HybridSearchRequest,
) -> HybridSearchResponse:
    try:
        result = hybrid_product_search(
            session,
            tenant_id=tenant_id,
            query=request.query,
            limit=request.limit,
        )
    except ValueError as exc:
        raise ApplicationError("SEARCH_QUERY_INVALID", str(exc)) from exc
    return HybridSearchResponse.model_validate(result)
