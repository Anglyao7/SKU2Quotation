from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog_translation_models import CatalogTranslationJobRow
from ..catalog_translation_schemas import (
    CatalogTranslationFailure,
    CatalogTranslationJobResponse,
    CatalogTranslationJobStartRequest,
    CatalogTranslationStatusResponse,
)
from ..database import SessionLocal, set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..repositories import catalog_translation_repository as translation_repository
from ..repositories import public_catalog_repository
from ..services.auth.dependencies import RequestContext
from ..services.catalog_translation import (
    CatalogTranslationSource,
    catalog_translation_source,
    translate_catalog_sources,
    translation_batches,
)
from ..services.translation import (
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)


logger = logging.getLogger(__name__)
_translation_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="catalog-translation",
)
_stale_job_after = timedelta(minutes=30)
_SOURCE_LOCALE = "zh-CN"
_FAILURE_DETAIL_LIMIT = 100


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {code}",
            kind="forbidden",
        )


def _positive_environment(
    name: str,
    default: int,
    *,
    maximum: int,
) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(value, maximum))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _job_response(job: CatalogTranslationJobRow) -> CatalogTranslationJobResponse:
    if job.total_skus == 0:
        progress = 100.0 if job.status == "SUCCEEDED" else 0.0
    else:
        progress = min(
            100.0,
            round(job.processed_skus / job.total_skus * 100, 1),
        )
    failures: list[CatalogTranslationFailure] = []
    for raw in job.failure_details or []:
        try:
            failures.append(CatalogTranslationFailure.model_validate(raw))
        except ValueError:
            continue
    return CatalogTranslationJobResponse(
        id=job.id,
        source_locale=job.source_locale,
        target_locale=job.target_locale,
        mode=job.mode,
        status=job.status,
        total_skus=job.total_skus,
        processed_skus=job.processed_skus,
        failed_skus=job.failed_skus,
        progress_percent=progress,
        current_sku_id=job.current_sku_id,
        current_sku_name=job.current_sku_name,
        provider=job.provider,
        provider_version=job.provider_version,
        failure_details=failures,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _active_job(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> CatalogTranslationJobRow | None:
    return session.scalar(
        select(CatalogTranslationJobRow)
        .where(
            CatalogTranslationJobRow.tenant_id == tenant_id,
            CatalogTranslationJobRow.target_locale == target_locale,
            CatalogTranslationJobRow.status.in_(("QUEUED", "RUNNING")),
        )
        .order_by(CatalogTranslationJobRow.created_at.desc())
        .limit(1)
    )


def _expire_stale_job(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> None:
    job = _active_job(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    if job is None or _as_utc(job.updated_at) >= utcnow() - _stale_job_after:
        return
    job.status = "FAILED"
    job.failed_skus = max(0, job.total_skus - job.processed_skus)
    job.error_message = "翻译任务因服务中断而停止，请重新发起。"
    job.current_sku_id = None
    job.current_sku_name = None
    job.completed_at = utcnow()
    session.commit()


def _all_sources(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[CatalogTranslationSource]:
    rows = public_catalog_repository.list_all_public_catalog_rows(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
    )
    return [catalog_translation_source(row) for row in rows]


def _pending_sources(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
    sources: list[CatalogTranslationSource],
    provider: str,
    provider_version: str,
    full_rebuild: bool,
) -> tuple[list[CatalogTranslationSource], int]:
    translations = translation_repository.translation_map(
        session,
        tenant_id=tenant_id,
        sku_ids=[source.sku_id for source in sources],
        target_locale=target_locale,
    )
    stale = 0
    pending: list[CatalogTranslationSource] = []
    for source in sources:
        translation = translations.get(source.sku_id)
        invalid = (
            translation is None
            or translation.source_hash != source.source_hash
            or translation.provider != provider
            or translation.provider_version != provider_version
        )
        if translation is not None and invalid:
            stale += 1
        if full_rebuild or invalid:
            pending.append(source)
    return pending, stale


def latest_translation_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    target_locale: str = "en-US",
) -> CatalogTranslationJobResponse | None:
    _require(permissions, "product.view")
    _expire_stale_job(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    job = session.scalar(
        select(CatalogTranslationJobRow)
        .where(
            CatalogTranslationJobRow.tenant_id == tenant_id,
            CatalogTranslationJobRow.target_locale == target_locale,
        )
        .order_by(CatalogTranslationJobRow.created_at.desc())
        .limit(1)
    )
    return _job_response(job) if job is not None else None


def get_translation_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: UUID,
) -> CatalogTranslationJobResponse:
    _require(permissions, "product.view")
    job = session.scalar(
        select(CatalogTranslationJobRow).where(
            CatalogTranslationJobRow.tenant_id == tenant_id,
            CatalogTranslationJobRow.id == job_id,
        )
    )
    if job is None:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_NOT_FOUND",
            "商品翻译任务不存在。",
            kind="not_found",
        )
    _expire_stale_job(
        session,
        tenant_id=tenant_id,
        target_locale=job.target_locale,
    )
    session.refresh(job)
    return _job_response(job)


def get_translation_status(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    target_locale: str = "en-US",
) -> CatalogTranslationStatusResponse:
    _require(permissions, "product.view")
    configured = catalog_translation_is_configured()
    provider = "deeplx" if configured else "not-configured"
    provider_version = "v1"
    if configured:
        try:
            translator = configured_catalog_translator()
            provider = translator.identity.provider
            provider_version = translator.identity.version
        except TranslationProviderError:
            configured = False

    sources = _all_sources(session, tenant_id=tenant_id)
    pending, stale = _pending_sources(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
        sources=sources,
        provider=provider,
        provider_version=provider_version,
        full_rebuild=False,
    )
    valid_count = max(0, len(sources) - len(pending))
    return CatalogTranslationStatusResponse(
        source_locale=_SOURCE_LOCALE,
        target_locale=target_locale,
        provider=provider,
        provider_version=provider_version,
        provider_configured=configured,
        total_skus=len(sources),
        translated_skus=valid_count,
        stale_skus=stale,
        pending_skus=len(pending),
        available_locales=list(
            dict.fromkeys(
                [
                    _SOURCE_LOCALE,
                    *translation_repository.available_target_locales(
                        session,
                        tenant_id=tenant_id,
                    ),
                ]
            )
        ),
        latest_job=latest_translation_job(
            session,
            tenant_id=tenant_id,
            permissions=permissions,
            target_locale=target_locale,
        ),
    )


def _safe_job_error(exc: Exception) -> str:
    if isinstance(exc, TranslationProviderError):
        return str(exc)
    return "商品翻译任务执行失败，请检查翻译服务配置或服务日志。"


def _failure_detail(
    source: CatalogTranslationSource,
    message: str,
) -> dict[str, str]:
    return {
        "sku_id": str(source.sku_id),
        "sku_code": source.sku_code,
        "name": source.name,
        "message": message,
    }


def _run_translation_job(
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
            select(CatalogTranslationJobRow).where(
                CatalogTranslationJobRow.tenant_id == tenant_id,
                CatalogTranslationJobRow.id == job_id,
            )
        )
        if job is None or job.status != "QUEUED":
            return
        try:
            translator = configured_catalog_translator()
            sources = _all_sources(session, tenant_id=tenant_id)
            candidates, _stale = _pending_sources(
                session,
                tenant_id=tenant_id,
                target_locale=job.target_locale,
                sources=sources,
                provider=translator.identity.provider,
                provider_version=translator.identity.version,
                full_rebuild=job.mode == "FULL_REBUILD",
            )
            job.status = "RUNNING"
            job.started_at = utcnow()
            job.provider = translator.identity.provider
            job.provider_version = translator.identity.version
            job.total_skus = len(candidates)
            job.processed_skus = 0
            job.failed_skus = 0
            job.failure_details = []
            session.commit()

            batches = translation_batches(
                candidates,
                max_items=_positive_environment(
                    "CATALOG_TRANSLATION_BATCH_SIZE",
                    5,
                    maximum=20,
                ),
                max_characters=_positive_environment(
                    "CATALOG_TRANSLATION_BATCH_CHARACTERS",
                    12_000,
                    maximum=50_000,
                ),
            )
            processed = 0
            failures: list[dict[str, str]] = []
            for batch in batches:
                job.current_sku_id = batch[0].sku_id
                job.current_sku_name = batch[0].name
                job.updated_at = utcnow()
                session.commit()
                try:
                    results = translate_catalog_sources(
                        translator,
                        batch,
                        source_locale=job.source_locale,
                        target_locale=job.target_locale,
                    )
                except TranslationProviderError as exc:
                    if (
                        len(batch) == 1
                        or "field structure" not in str(exc)
                    ):
                        raise
                    results = []
                    for source in batch:
                        try:
                            results.extend(
                                translate_catalog_sources(
                                    translator,
                                    [source],
                                    source_locale=job.source_locale,
                                    target_locale=job.target_locale,
                                )
                            )
                        except TranslationProviderError as item_exc:
                            if len(failures) < _FAILURE_DETAIL_LIMIT:
                                failures.append(
                                    _failure_detail(source, str(item_exc))
                                )

                source_by_id = {source.sku_id: source for source in batch}
                translated_ids: set[UUID] = set()
                for result in results:
                    source = source_by_id[result.sku_id]
                    translation_repository.save_translation(
                        session,
                        tenant_id=tenant_id,
                        source_locale=job.source_locale,
                        target_locale=job.target_locale,
                        source=source,
                        result=result,
                        provider=translator.identity.provider,
                        provider_version=translator.identity.version,
                    )
                    translated_ids.add(result.sku_id)
                failed_in_batch = len(batch) - len(translated_ids)
                processed += len(batch)
                job.processed_skus = processed
                job.failed_skus += failed_in_batch
                job.failure_details = failures
                job.updated_at = utcnow()
                session.commit()

            job.status = "SUCCEEDED"
            job.current_sku_id = None
            job.current_sku_name = None
            job.completed_at = utcnow()
            session.commit()
        except Exception as exc:
            logger.exception("catalog translation job %s failed", job_id)
            session.rollback()
            failed_job = session.scalar(
                select(CatalogTranslationJobRow).where(
                    CatalogTranslationJobRow.tenant_id == tenant_id,
                    CatalogTranslationJobRow.id == job_id,
                )
            )
            if failed_job is None:
                return
            failed_job.status = "FAILED"
            failed_job.failed_skus = max(
                failed_job.failed_skus,
                failed_job.total_skus - failed_job.processed_skus,
            )
            failed_job.error_message = _safe_job_error(exc)
            failed_job.current_sku_id = None
            failed_job.current_sku_name = None
            failed_job.completed_at = utcnow()
            session.commit()


def _dispatch_translation_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    _translation_executor.submit(
        _run_translation_job,
        job_id=job_id,
        organization_id=organization_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def start_translation_job(
    session: Session,
    *,
    context: RequestContext,
    request: CatalogTranslationJobStartRequest,
) -> CatalogTranslationJobResponse:
    _require(context.permissions, "product.edit")
    if request.mode == "FULL_REBUILD" and not request.confirm_full_rebuild:
        raise ApplicationError(
            "CATALOG_TRANSLATION_REBUILD_CONFIRMATION_REQUIRED",
            "全量重新翻译需要明确确认。",
        )
    try:
        translator = configured_catalog_translator()
    except TranslationProviderError as exc:
        raise ApplicationError(
            "CATALOG_TRANSLATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc

    _expire_stale_job(
        session,
        tenant_id=context.tenant_id,
        target_locale=request.target_locale,
    )
    existing = _active_job(
        session,
        tenant_id=context.tenant_id,
        target_locale=request.target_locale,
    )
    if existing is not None:
        return _job_response(existing)

    sources = _all_sources(session, tenant_id=context.tenant_id)
    candidates, _stale = _pending_sources(
        session,
        tenant_id=context.tenant_id,
        target_locale=request.target_locale,
        sources=sources,
        provider=translator.identity.provider,
        provider_version=translator.identity.version,
        full_rebuild=request.mode == "FULL_REBUILD",
    )
    now = utcnow()
    job = CatalogTranslationJobRow(
        tenant_id=context.tenant_id,
        requested_by_membership_id=context.membership_id,
        requested_by_user_id=context.user_id,
        source_locale=_SOURCE_LOCALE,
        target_locale=request.target_locale,
        mode=request.mode,
        status="SUCCEEDED" if not candidates else "QUEUED",
        total_skus=len(candidates),
        processed_skus=0,
        failed_skus=0,
        provider=translator.identity.provider,
        provider_version=translator.identity.version,
        failure_details=[],
        completed_at=now if not candidates else None,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = _active_job(
            session,
            tenant_id=context.tenant_id,
            target_locale=request.target_locale,
        )
        if existing is not None:
            return _job_response(existing)
        raise ApplicationError(
            "CATALOG_TRANSLATION_BUSY",
            "当前商家的商品翻译任务正在执行，请稍后再试。",
            kind="conflict",
        ) from exc

    if candidates:
        try:
            _dispatch_translation_job(
                job_id=job.id,
                organization_id=context.organization_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except RuntimeError as exc:
            job.status = "FAILED"
            job.failed_skus = len(candidates)
            job.error_message = "翻译任务暂时无法启动，请稍后重试。"
            job.completed_at = utcnow()
            session.commit()
            raise ApplicationError(
                "CATALOG_TRANSLATION_DISPATCH_FAILED",
                job.error_message,
            ) from exc
    return _job_response(job)
