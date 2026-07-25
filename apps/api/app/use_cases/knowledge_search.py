from __future__ import annotations

from dataclasses import asdict
from threading import Lock
from uuid import UUID

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..knowledge_embedding_schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeIndexStatusResponse,
    KnowledgeIndexUpdateResponse,
    KnowledgeProjectionResponse,
)
from ..services.hybrid_search import hybrid_product_search
from ..services.knowledge import (
    KnowledgeProjectionError,
    knowledge_index_status,
    project_product_knowledge,
    update_knowledge_index,
)


_index_guard = Lock()
_active_index_tenants: set[UUID] = set()


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {code}",
            kind="forbidden",
        )


def project_product(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    product_id: UUID,
) -> KnowledgeProjectionResponse:
    _require(permissions, "product.edit")
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


def get_index_status(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> KnowledgeIndexStatusResponse:
    _require(permissions, "product.view")
    try:
        result = knowledge_index_status(session, tenant_id=tenant_id)
    except ValueError as exc:
        raise ApplicationError("KNOWLEDGE_INDEX_CONFIGURATION_INVALID", str(exc)) from exc
    return KnowledgeIndexStatusResponse(**asdict(result))


def update_index(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    full_rebuild: bool,
) -> KnowledgeIndexUpdateResponse:
    _require(permissions, "product.edit")
    with _index_guard:
        if tenant_id in _active_index_tenants:
            raise ApplicationError(
                "KNOWLEDGE_INDEX_BUSY",
                "当前商家的智能索引正在更新，请稍后再试。",
                kind="conflict",
            )
        _active_index_tenants.add(tenant_id)
    try:
        result = update_knowledge_index(
            session,
            tenant_id=tenant_id,
            full_rebuild=full_rebuild,
        )
    except ValueError as exc:
        session.rollback()
        raise ApplicationError(
            "KNOWLEDGE_INDEX_UPDATE_FAILED",
            f"智能索引更新失败：{exc}",
        ) from exc
    finally:
        with _index_guard:
            _active_index_tenants.discard(tenant_id)
    return KnowledgeIndexUpdateResponse(**asdict(result))


def search_products(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: HybridSearchRequest,
) -> HybridSearchResponse:
    _require(permissions, "product.view")
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
