from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import UUID

import psycopg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import SessionLocal, set_request_context
from ..domain.errors import ApplicationError
from ..embedding_management_models import KnowledgeIndexJobRow
from ..identity_models import TenantRow
from ..knowledge_embedding_schemas import (
    AISearchRecommendedQuestionsResponse,
    AISearchRecommendedQuestionsUpdate,
    DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS,
    HybridSearchRequest,
    HybridSearchResponse,
    KnowledgeIndexJobResponse,
    KnowledgeIndexJobStartRequest,
    KnowledgeIndexStatusResponse,
    KnowledgeIndexUpdateResponse,
    KnowledgeProjectionResponse,
    PopularSearchTerm,
    PopularSearchTermsResponse,
)
from ..model_mixins import utcnow
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import search_analytics_repository
from ..services.auth.dependencies import RequestContext
from ..services.embedding import EmbeddingProviderError
from ..services.embedding_configuration import resolved_text_embedding_provider
from ..services.hybrid_search import hybrid_product_search
from ..services.knowledge import (
    KnowledgeProjectionError,
    indexed_product_ids,
    knowledge_index_status,
    knowledge_index_target_products,
    knowledge_projection_policy_mismatch_exists,
    project_product_knowledge,
    update_knowledge_index,
)
from ..services.search_analytics import popular_search_window


_index_guard = Lock()
_active_index_tenants: set[UUID] = set()
_index_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="knowledge-index",
)
_stale_job_after = timedelta(minutes=10)
logger = logging.getLogger(__name__)
_ZERO_IDENTITY = UUID(int=0)


def _normalized_recommended_questions(value: object) -> list[str]:
    """Return up to five safe questions for the public storefront."""

    if not isinstance(value, list):
        return list(DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        question = str(item).strip()[:200]
        key = question.casefold()
        if not question or key in seen:
            continue
        seen.add(key)
        normalized.append(question)
    return normalized[:5] or list(DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS)


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


def get_recommended_questions(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> AISearchRecommendedQuestionsResponse:
    _require(permissions, "product.view")
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id,
        )
    )
    questions = _normalized_recommended_questions(
        profile.ai_search_questions if profile is not None else None,
    )
    return AISearchRecommendedQuestionsResponse(questions=questions)


def get_popular_search_terms(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    days: int,
    limit: int,
) -> PopularSearchTermsResponse:
    _require(permissions, "product.view")
    start_date, end_date = popular_search_window(days=days)
    rows = search_analytics_repository.list_popular_search_terms(
        session,
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return PopularSearchTermsResponse(
        days=days,
        items=[
            PopularSearchTerm(
                term=str(row["term_display"] or row["term_normalized"]),
                count=int(row["search_count"] or 0),
                last_searched_at=row["last_searched_at"],
            )
            for row in rows
        ],
    )


def update_recommended_questions(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: AISearchRecommendedQuestionsUpdate,
) -> AISearchRecommendedQuestionsResponse:
    _require(permissions, "product.edit")
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant_id,
        )
    )
    if profile is None:
        tenant = session.get(TenantRow, tenant_id)
        if tenant is None:
            raise ApplicationError(
                "TENANT_NOT_FOUND",
                "Merchant workspace was not found.",
                kind="not_found",
            )
        profile = TenantPublicProfileRow(
            tenant_id=tenant_id,
            slug=tenant.slug,
            publication_status=(
                "PUBLISHED" if tenant.status == "active" else "SUSPENDED"
            ),
        )
        session.add(profile)
        session.flush()
    profile.ai_search_questions = list(request.questions)
    session.commit()
    return AISearchRecommendedQuestionsResponse(
        questions=_normalized_recommended_questions(profile.ai_search_questions),
    )


def _remaining_product_ids(job: KnowledgeIndexJobRow) -> list[UUID]:
    values: list[UUID] = []
    for raw in job.remaining_product_ids or []:
        try:
            values.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return list(dict.fromkeys(values))


def _job_response(job: KnowledgeIndexJobRow) -> KnowledgeIndexJobResponse:
    if job.total_products == 0:
        progress_percent = 100.0 if job.status == "SUCCEEDED" else 0.0
    else:
        progress_percent = min(
            100.0,
            round(job.processed_products / job.total_products * 100, 1),
        )
    remaining_products = len(_remaining_product_ids(job))
    if remaining_products == 0 and job.processed_products < job.total_products:
        remaining_products = job.total_products - job.processed_products
    return KnowledgeIndexJobResponse(
        id=job.id,
        mode=job.mode,
        status=job.status,
        total_products=job.total_products,
        processed_products=job.processed_products,
        failed_products=job.failed_products,
        embeddings=job.embeddings,
        remaining_products=remaining_products,
        progress_percent=progress_percent,
        current_product_id=job.current_product_id,
        current_product_name=job.current_product_name,
        error_message=job.error_message,
        pause_requested=(
            job.status in {"QUEUED", "RUNNING"}
            and job.pause_requested_at is not None
        ),
        pause_requested_at=job.pause_requested_at,
        paused_at=job.paused_at,
        resumable=job.status in {"PAUSED", "FAILED"},
        checkpoint_at=(
            job.updated_at
            if job.started_at is not None or job.processed_products > 0
            else None
        ),
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
            KnowledgeIndexJobRow.status.in_(("QUEUED", "RUNNING", "PAUSED")),
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
    if active is None or active.status == "PAUSED":
        return
    if _as_utc(active.updated_at) >= utcnow() - _stale_job_after:
        return
    active.status = "PAUSED"
    active.failed_products = 0
    active.error_message = "索引服务曾中断，已保留最近批次的断点，可继续向量化。"
    active.current_product_id = None
    active.current_product_name = None
    active.pause_requested_at = None
    active.paused_at = utcnow()
    active.completed_at = None
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


def _pause_at_safe_checkpoint(
    session: Session,
    job: KnowledgeIndexJobRow,
) -> bool:
    """Acknowledge a cross-process pause request between embedding batches."""

    session.refresh(
        job,
        attribute_names=("status", "pause_requested_at", "updated_at"),
    )
    if job.status == "PAUSED":
        return True
    if job.status != "RUNNING":
        return True
    if job.pause_requested_at is None:
        return False
    now = utcnow()
    job.status = "PAUSED"
    job.failed_products = 0
    job.paused_at = now
    job.current_product_id = None
    job.current_product_name = None
    job.updated_at = now
    session.commit()
    return True


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
                KnowledgeIndexJobRow.status == "QUEUED",
            ).with_for_update(skip_locked=True)
        )
        if job is None:
            return
        try:
            embedder = resolved_text_embedding_provider(session)
            identity = embedder.identity
            identity_changed = (
                job.model_provider,
                job.model_name,
                job.model_version,
                job.dimensions,
            ) != (
                identity.provider,
                identity.model_name,
                identity.model_version,
                identity.dimensions,
            )
            stored_remaining = _remaining_product_ids(job)
            projection_policy_changed = False
            if job.started_at is not None and job.processed_products > 0:
                if job.mode == "FULL_REBUILD":
                    all_eligible_products = knowledge_index_target_products(
                        session,
                        tenant_id=tenant_id,
                        full_rebuild=True,
                        embedder=embedder,
                    )
                    remaining_ids = set(stored_remaining)
                    checkpointed_ids = [
                        product_id
                        for product_id, _name in all_eligible_products
                        if product_id not in remaining_ids
                    ]
                    projection_policy_changed = (
                        knowledge_projection_policy_mismatch_exists(
                            session,
                            tenant_id=tenant_id,
                            product_ids=checkpointed_ids,
                        )
                    )
                elif knowledge_projection_policy_mismatch_exists(
                    session,
                    tenant_id=tenant_id,
                ):
                    projection_policy_changed = (
                        len(
                            indexed_product_ids(
                                session,
                                tenant_id=tenant_id,
                                embedder=embedder,
                            )
                        )
                        < job.processed_products
                    )
            if identity_changed or projection_policy_changed:
                target_products = knowledge_index_target_products(
                    session,
                    tenant_id=tenant_id,
                    full_rebuild=job.mode == "FULL_REBUILD",
                    embedder=embedder,
                )
                job.processed_products = 0
                job.embeddings = 0
            elif stored_remaining or (
                job.started_at is not None
                and job.processed_products >= job.total_products
            ):
                target_products = knowledge_index_target_products(
                    session,
                    tenant_id=tenant_id,
                    full_rebuild=job.mode == "FULL_REBUILD",
                    embedder=embedder,
                    product_ids=stored_remaining,
                )
                if job.started_at is not None:
                    target_ids = {
                        product_id for product_id, _name in target_products
                    }
                    newly_pending = knowledge_index_target_products(
                        session,
                        tenant_id=tenant_id,
                        full_rebuild=False,
                        embedder=embedder,
                    )
                    target_products.extend(
                        (product_id, product_name)
                        for product_id, product_name in newly_pending
                        if product_id not in target_ids
                    )
            elif job.processed_products < job.total_products:
                # Legacy jobs did not persist target IDs. Current-model pending
                # rows are the safe recovery set and avoid repeating committed work.
                target_products = knowledge_index_target_products(
                    session,
                    tenant_id=tenant_id,
                    full_rebuild=False,
                    embedder=embedder,
                )
            else:
                target_products = []

            target_ids = [product_id for product_id, _name in target_products]
            base_processed = job.processed_products
            base_embeddings = job.embeddings
            job.status = "RUNNING"
            if job.started_at is None:
                job.started_at = utcnow()
            job.model_provider = identity.provider
            job.model_name = identity.model_name
            job.model_version = identity.model_version
            job.dimensions = identity.dimensions
            job.total_products = base_processed + len(target_ids)
            job.remaining_product_ids = [str(product_id) for product_id in target_ids]
            job.failed_products = 0
            job.error_message = None
            job.paused_at = None
            job.completed_at = None
            session.commit()

            if _pause_at_safe_checkpoint(session, job):
                return

            def record_progress(
                processed: int,
                total: int,
                embeddings: int,
                current_product_id: UUID | None,
                current_product_name: str | None,
            ) -> None:
                job.total_products = base_processed + total
                job.processed_products = base_processed + processed
                job.embeddings = base_embeddings + embeddings
                job.remaining_product_ids = [
                    str(product_id) for product_id in target_ids[processed:]
                ]
                job.current_product_id = current_product_id
                job.current_product_name = current_product_name
                job.updated_at = utcnow()

            result = update_knowledge_index(
                session,
                tenant_id=tenant_id,
                full_rebuild=job.mode == "FULL_REBUILD",
                embedder=embedder,
                target_product_ids=target_ids,
                progress_callback=record_progress,
                pause_callback=lambda: _pause_at_safe_checkpoint(session, job),
            )
            if result.paused:
                return

            completed_job = session.scalar(
                select(KnowledgeIndexJobRow)
                .where(
                    KnowledgeIndexJobRow.tenant_id == tenant_id,
                    KnowledgeIndexJobRow.id == job_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if completed_job is None:
                return
            if completed_job.pause_requested_at is not None:
                now = utcnow()
                completed_job.status = "PAUSED"
                completed_job.failed_products = 0
                completed_job.paused_at = now
                completed_job.current_product_id = None
                completed_job.current_product_name = None
                completed_job.updated_at = now
                session.commit()
                return
            if completed_job.status != "RUNNING":
                session.rollback()
                return
            completed_job.status = "SUCCEEDED"
            completed_job.processed_products = completed_job.total_products
            completed_job.remaining_product_ids = []
            completed_job.failed_products = 0
            completed_job.current_product_id = None
            completed_job.current_product_name = None
            completed_job.pause_requested_at = None
            completed_job.paused_at = None
            completed_job.error_message = None
            completed_job.completed_at = utcnow()
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
                len(_remaining_product_ids(failed_job)),
                failed_job.total_products - failed_job.processed_products,
            )
            failed_job.error_message = (
                f"{_safe_job_error(exc)} 已完成批次和向量已保留，可从断点继续。"
            )
            failed_job.current_product_id = None
            failed_job.current_product_name = None
            failed_job.pause_requested_at = None
            failed_job.paused_at = None
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


def _index_job_tenant_ids(session: Session) -> tuple[UUID, ...]:
    dialect = session.bind.dialect.name if session.bind is not None else "unknown"
    if dialect != "postgresql":
        return tuple(
            session.scalars(
                select(KnowledgeIndexJobRow.tenant_id)
                .where(
                    KnowledgeIndexJobRow.status.in_(("QUEUED", "RUNNING")),
                    KnowledgeIndexJobRow.deleted_at.is_(None),
                )
                .distinct()
            ).all()
        )

    directory_url = os.getenv("TENANT_DIRECTORY_DATABASE_URL", "").strip()
    if not directory_url:
        logger.warning(
            "knowledge index checkpoint recovery skipped: tenant directory is not configured"
        )
        return ()
    psycopg_url = directory_url.replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )
    try:
        with psycopg.connect(psycopg_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL ORDER BY id"
                )
                return tuple(UUID(str(row[0])) for row in cursor.fetchall())
    except psycopg.Error:
        logger.exception(
            "knowledge index checkpoint recovery could not read tenant directory"
        )
        return ()


def recover_interrupted_index_jobs() -> int:
    """Turn process-owned unfinished jobs into resumable checkpoints."""

    with SessionLocal() as session:
        tenant_ids = _index_job_tenant_ids(session)
        session.rollback()

    recovered = 0
    for tenant_id in tenant_ids:
        try:
            with SessionLocal() as session:
                set_request_context(
                    session,
                    organization_id=_ZERO_IDENTITY,
                    tenant_id=tenant_id,
                    user_id=_ZERO_IDENTITY,
                )
                interrupted = list(
                    session.scalars(
                        select(KnowledgeIndexJobRow).where(
                            KnowledgeIndexJobRow.tenant_id == tenant_id,
                            KnowledgeIndexJobRow.status.in_(("QUEUED", "RUNNING")),
                            KnowledgeIndexJobRow.deleted_at.is_(None),
                        )
                    ).all()
                )
                if not interrupted:
                    session.rollback()
                    continue
                now = utcnow()
                for job in interrupted:
                    job.status = "PAUSED"
                    job.failed_products = 0
                    job.pause_requested_at = None
                    job.paused_at = now
                    job.current_product_id = None
                    job.current_product_name = None
                    job.error_message = (
                        "服务重启前的向量化进度已保存，可从最近完成的批次继续。"
                    )
                    job.completed_at = None
                    job.updated_at = now
                session.commit()
                recovered += len(interrupted)
        except Exception:
            logger.exception(
                "knowledge index checkpoint recovery failed for tenant %s",
                tenant_id,
            )
    return recovered


def _managed_job(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
    for_update: bool = False,
) -> KnowledgeIndexJobRow:
    statement = select(KnowledgeIndexJobRow).where(
        KnowledgeIndexJobRow.tenant_id == tenant_id,
        KnowledgeIndexJobRow.id == job_id,
    )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_JOB_NOT_FOUND",
            "智能索引任务不存在。",
            kind="not_found",
        )
    return job


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
        target_products = knowledge_index_target_products(
            session,
            tenant_id=context.tenant_id,
            full_rebuild=request.mode == "FULL_REBUILD",
            embedder=embedder,
        )
    except (ValueError, EmbeddingProviderError) as exc:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_CONFIGURATION_INVALID",
            str(exc),
        ) from exc

    target_ids = [product_id for product_id, _name in target_products]
    total_products = len(target_ids)
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
        remaining_product_ids=[str(product_id) for product_id in target_ids],
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


def pause_index_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> KnowledgeIndexJobResponse:
    _require(context.permissions, "product.edit")
    job = _managed_job(
        session,
        tenant_id=context.tenant_id,
        job_id=job_id,
        for_update=True,
    )
    if job.status == "PAUSED":
        return _job_response(job)
    if job.status not in {"QUEUED", "RUNNING"}:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_JOB_NOT_PAUSABLE",
            "当前向量化任务已经结束，无法暂停。",
            kind="conflict",
        )
    now = utcnow()
    job.pause_requested_at = now
    if job.status == "QUEUED":
        job.status = "PAUSED"
        job.paused_at = now
        job.current_product_id = None
        job.current_product_name = None
    session.commit()
    return _job_response(job)


def resume_index_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> KnowledgeIndexJobResponse:
    _require(context.permissions, "product.edit")
    job = _managed_job(
        session,
        tenant_id=context.tenant_id,
        job_id=job_id,
        for_update=True,
    )
    if job.status == "RUNNING" and job.pause_requested_at is not None:
        job.pause_requested_at = None
        session.commit()
        return _job_response(job)
    if job.status not in {"PAUSED", "FAILED"}:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_JOB_NOT_RESUMABLE",
            "只有已暂停或中断的向量化任务可以继续。",
            kind="conflict",
        )
    existing = _active_job(session, tenant_id=context.tenant_id)
    if existing is not None and existing.id != job.id:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_JOB_CONFLICT",
            "当前商家已有另一个向量化任务。",
            kind="conflict",
        )

    try:
        embedder = resolved_text_embedding_provider(session)
    except (ValueError, EmbeddingProviderError) as exc:
        raise ApplicationError(
            "KNOWLEDGE_INDEX_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    identity = embedder.identity
    identity_changed = (
        job.model_provider,
        job.model_name,
        job.model_version,
        job.dimensions,
    ) != (
        identity.provider,
        identity.model_name,
        identity.model_version,
        identity.dimensions,
    )
    remaining_ids = _remaining_product_ids(job)
    if identity_changed or (
        not remaining_ids and job.processed_products < job.total_products
    ):
        targets = knowledge_index_target_products(
            session,
            tenant_id=context.tenant_id,
            full_rebuild=(
                job.mode == "FULL_REBUILD" if identity_changed else False
            ),
            embedder=embedder,
        )
        remaining_ids = [product_id for product_id, _name in targets]
        if identity_changed:
            job.processed_products = 0
            job.embeddings = 0
            job.model_provider = identity.provider
            job.model_name = identity.model_name
            job.model_version = identity.model_version
            job.dimensions = identity.dimensions
        job.total_products = job.processed_products + len(remaining_ids)
        job.remaining_product_ids = [
            str(product_id) for product_id in remaining_ids
        ]

    job.status = "QUEUED"
    job.pause_requested_at = None
    job.paused_at = None
    job.failed_products = 0
    job.error_message = None
    job.current_product_id = None
    job.current_product_name = None
    job.completed_at = None
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "KNOWLEDGE_INDEX_JOB_CONFLICT",
            "当前商家已有另一个向量化任务。",
            kind="conflict",
        ) from exc
    try:
        _dispatch_index_job(
            job_id=job.id,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except RuntimeError as exc:
        job.status = "PAUSED"
        job.paused_at = utcnow()
        job.error_message = "向量化任务暂时无法继续，请稍后重试。"
        session.commit()
        raise ApplicationError(
            "KNOWLEDGE_INDEX_RESUME_FAILED",
            job.error_message,
        ) from exc
    return _job_response(job)
