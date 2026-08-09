from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import SessionLocal, set_request_context
from ..domain.errors import ApplicationError
from ..embedding_management_models import KnowledgeIndexJobRow
from ..knowledge_embedding_schemas import (
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeIndexJobResponse,
    KnowledgeIndexJobStartRequest,
    KnowledgeIndexStatusResponse,
    KnowledgeIndexUpdateResponse,
    KnowledgeProjectionResponse,
)
from ..model_mixins import utcnow
from ..services.auth.dependencies import RequestContext
from ..services.embedding import EmbeddingProviderError
from ..services.embedding_configuration import resolved_text_embedding_provider
from ..services.hybrid_search import hybrid_product_search
from ..services.knowledge import (
    KnowledgeProjectionError,
    knowledge_index_status,
    project_product_knowledge,
    update_knowledge_index,
)


_index_guard = Lock()
_active_index_tenants: set[UUID] = set()
_index_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="knowledge-index",
)
_stale_job_after = timedelta(minutes=10)
logger = logging.getLogger(__name__)


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
        embedder = resolved_text_embedding_provider(session)
        result = project_product_knowledge(
            session,
            tenant_id=tenant_id,
            product_id=product_id,
            embedder=embedder,
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
        result = knowledge_index_status(
            session,
            tenant_id=tenant_id,
            embedder=resolved_text_embedding_provider(session),
        )
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
        embedder = resolved_text_embedding_provider(session)
        result = update_knowledge_index(
            session,
            tenant_id=tenant_id,
            full_rebuild=full_rebuild,
            embedder=embedder,
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
            embedder=resolved_text_embedding_provider(session),
        )
    except ValueError as exc:
        raise ApplicationError("SEARCH_QUERY_INVALID", str(exc)) from exc
    result["degraded"] = bool(result.get("degraded_channels"))
    return HybridSearchResponse.model_validate(result)


def _job_response(job: KnowledgeIndexJobRow) -> KnowledgeIndexJobResponse:
    if job.total_products == 0:
        progress_percent = 100.0 if job.status == "SUCCEEDED" else 0.0
    else:
        progress_percent = min(
            100.0,
            round(job.processed_products / job.total_products * 100, 1),
        )
    return KnowledgeIndexJobResponse(
        id=job.id,
        mode=job.mode,
        status=job.status,
        total_products=job.total_products,
        processed_products=job.processed_products,
        failed_products=job.failed_products,
        embeddings=job.embeddings,
        progress_percent=progress_percent,
        current_product_id=job.current_product_id,
        current_product_name=job.current_product_name,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _active_job(
    session: Session,
    *,
    tenant_id: UUID,
) -> KnowledgeIndexJobRow | None:
    return session.scalar(
        select(KnowledgeIndexJobRow)
        .where(
            KnowledgeIndexJobRow.tenant_id == tenant_id,
            KnowledgeIndexJobRow.status.in_(("QUEUED", "RUNNING")),
        )
        .order_by(KnowledgeIndexJobRow.created_at.desc())
        .limit(1)
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _expire_stale_job(
    session: Session,
    *,
    tenant_id: UUID,
) -> None:
    active = _active_job(session, tenant_id=tenant_id)
    if active is None:
        return
    if _as_utc(active.updated_at) >= utcnow() - _stale_job_after:
        return
    active.status = "FAILED"
    active.failed_products = max(
        0,
        active.total_products - active.processed_products,
    )
    active.error_message = "索引任务因服务中断而停止，请重新发起。"
    active.current_product_id = None
    active.current_product_name = None
    active.completed_at = utcnow()
    session.commit()


def latest_index_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> KnowledgeIndexJobResponse | None:
    _require(permissions, "product.view")
    _expire_stale_job(session, tenant_id=tenant_id)
    job = session.scalar(
        select(KnowledgeIndexJobRow)
        .where(KnowledgeIndexJobRow.tenant_id == tenant_id)
        .order_by(KnowledgeIndexJobRow.created_at.desc())
        .limit(1)
    )
    return _job_response(job) if job is not None else None


def get_index_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: UUID,
) -> KnowledgeIndexJobResponse:
    _require(permissions, "product.view")
    _expire_stale_job(session, tenant_id=tenant_id)
    job = session.scalar(
        select(KnowledgeIndexJobRow).where(
            KnowledgeIndexJobRow.tenant_id == tenant_id,
            KnowledgeIndexJobRow.id == job_id,
        )
    )
    if job is None:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_JOB_NOT_FOUND",
            "智能索引任务不存在。",
            kind="not_found",
        )
    return _job_response(job)


def _safe_job_error(exc: Exception) -> str:
    if isinstance(exc, (ValueError, EmbeddingProviderError)):
        return str(exc)
    return "智能索引任务执行失败，请检查模型配置或服务日志。"


def _run_index_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        job = session.scalar(
            select(KnowledgeIndexJobRow).where(
                KnowledgeIndexJobRow.tenant_id == tenant_id,
                KnowledgeIndexJobRow.id == job_id,
            )
        )
        if job is None or job.status != "QUEUED":
            return
        try:
            embedder = resolved_text_embedding_provider(session)
            job.status = "RUNNING"
            job.started_at = utcnow()
            job.model_provider = embedder.identity.provider
            job.model_name = embedder.identity.model_name
            job.model_version = embedder.identity.model_version
            job.dimensions = embedder.identity.dimensions
            session.commit()

            def record_progress(
                processed: int,
                total: int,
                embeddings: int,
                current_product_id: UUID | None,
                current_product_name: str | None,
            ) -> None:
                job.total_products = total
                job.processed_products = processed
                job.embeddings = embeddings
                job.current_product_id = current_product_id
                job.current_product_name = current_product_name
                job.updated_at = utcnow()

            result = update_knowledge_index(
                session,
                tenant_id=tenant_id,
                full_rebuild=job.mode == "FULL_REBUILD",
                embedder=embedder,
                progress_callback=record_progress,
            )
            job.status = "SUCCEEDED"
            job.total_products = result.processed_products
            job.processed_products = result.processed_products
            job.embeddings = result.embeddings
            job.failed_products = 0
            job.current_product_id = None
            job.current_product_name = None
            job.completed_at = utcnow()
            session.commit()
        except Exception as exc:
            logger.exception("knowledge index job %s failed", job_id)
            session.rollback()
            failed_job = session.scalar(
                select(KnowledgeIndexJobRow).where(
                    KnowledgeIndexJobRow.tenant_id == tenant_id,
                    KnowledgeIndexJobRow.id == job_id,
                )
            )
            if failed_job is None:
                return
            failed_job.status = "FAILED"
            failed_job.failed_products = max(
                0,
                failed_job.total_products - failed_job.processed_products,
            )
            failed_job.error_message = _safe_job_error(exc)
            failed_job.current_product_id = None
            failed_job.current_product_name = None
            failed_job.completed_at = utcnow()
            session.commit()


def _dispatch_index_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    _index_executor.submit(
        _run_index_job,
        job_id=job_id,
        organization_id=organization_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def start_index_job(
    session: Session,
    *,
    context: RequestContext,
    request: KnowledgeIndexJobStartRequest,
) -> KnowledgeIndexJobResponse:
    _require(context.permissions, "product.edit")
    if request.mode == "FULL_REBUILD" and not request.confirm_full_rebuild:
        raise ApplicationError(
            "FULL_REBUILD_CONFIRMATION_REQUIRED",
            "全量重建需要明确确认。",
        )
    _expire_stale_job(session, tenant_id=context.tenant_id)
    existing = _active_job(session, tenant_id=context.tenant_id)
    if existing is not None:
        return _job_response(existing)

    try:
        embedder = resolved_text_embedding_provider(session)
        index_status = knowledge_index_status(
            session,
            tenant_id=context.tenant_id,
            embedder=embedder,
        )
    except (ValueError, EmbeddingProviderError) as exc:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_CONFIGURATION_INVALID",
            str(exc),
        ) from exc

    total_products = (
        index_status.total_products
        if request.mode == "FULL_REBUILD"
        else index_status.pending_products
    )
    now = utcnow()
    job = KnowledgeIndexJobRow(
        tenant_id=context.tenant_id,
        requested_by_membership_id=context.membership_id,
        requested_by_user_id=context.user_id,
        mode=request.mode,
        status="SUCCEEDED" if total_products == 0 else "QUEUED",
        total_products=total_products,
        processed_products=0,
        model_provider=embedder.identity.provider,
        model_name=embedder.identity.model_name,
        model_version=embedder.identity.model_version,
        dimensions=embedder.identity.dimensions,
        completed_at=now if total_products == 0 else None,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = _active_job(session, tenant_id=context.tenant_id)
        if existing is not None:
            return _job_response(existing)
        raise ApplicationError(
            "KNOWLEDGE_INDEX_BUSY",
            "当前商家的智能索引正在更新，请稍后再试。",
            kind="conflict",
        ) from exc

    if total_products > 0:
        try:
            _dispatch_index_job(
                job_id=job.id,
                organization_id=context.organization_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except RuntimeError as exc:
            job.status = "FAILED"
            job.failed_products = total_products
            job.error_message = "索引任务暂时无法启动，请稍后重试。"
            job.completed_at = utcnow()
            session.commit()
            raise ApplicationError(
                "KNOWLEDGE_INDEX_JOB_DISPATCH_FAILED",
                job.error_message,
            ) from exc
    return _job_response(job)
