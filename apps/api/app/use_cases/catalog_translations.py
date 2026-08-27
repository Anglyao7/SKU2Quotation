from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

import psycopg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from ..catalog_translation_models import (
    CatalogLanguagePackRow,
    CatalogTranslationBatchAttemptRow,
    CatalogTranslationBatchRow,
    CatalogTranslationJobRow,
)
from ..catalog_translation_schemas import (
    CatalogTranslationBatchAttemptResponse,
    CatalogTranslationBatchResponse,
    CatalogTranslationFailure,
    CatalogTranslationJobResponse,
    CatalogTranslationProductRetryRequest,
    CatalogTranslationJobStartRequest,
    CatalogLanguagePackResponse,
    CatalogTranslationStatusResponse,
)
from ..database import (
    SessionLocal,
    set_public_tenant_context,
    set_request_context,
)
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..repositories import catalog_translation_repository as translation_repository
from ..repositories import public_catalog_repository
from ..services.auth.dependencies import RequestContext
from ..services.catalog_translation import (
    CatalogTranslationResult,
    CatalogTranslationSource,
    catalog_translation_source,
    translate_catalog_sources,
    translation_batches,
)
from ..services.catalog_language_packages import (
    build_catalog_language_pack,
    catalog_rows_source_digest,
    language_pack_object_key,
    load_language_pack_payload,
)
from ..services.language_package_storage import (
    configured_language_package_storage,
    language_package_storage_status,
)
from ..services.translation import (
    TranslationProvider,
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)
from ..services.translation_configuration import (
    resolved_catalog_translation_batch_limits,
    resolved_catalog_translation_concurrency,
    resolved_catalog_translation_retry_count,
    resolved_catalog_translator,
    translation_provider_is_configured,
)
from ..storefront_locales import (
    effective_storefront_locales,
    normalize_storefront_locale,
)


logger = logging.getLogger(__name__)
_translation_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="catalog-translation",
)
_stale_job_after = timedelta(minutes=30)
_SOURCE_LOCALE = "zh-CN"
_FAILURE_DETAIL_LIMIT = 100
_ZERO_IDENTITY = UUID(int=0)
_TRANSIENT_TRANSLATION_ERRORS = (
    "timed out",
    "request failed",
    "temporarily",
    "rate limit",
    "throttl",
    "too many requests",
    "http 408",
    "http 409",
    "http 425",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


@dataclass(frozen=True)
class _BatchAttemptEvent:
    attempt_no: int
    request_started_at: datetime
    first_byte_at: datetime | None
    completed_at: datetime
    status: str
    processed_skus: int
    failed_skus: int
    error_message: str | None = None


@dataclass(frozen=True)
class _BatchTranslationOutcome:
    results: list[CatalogTranslationResult] | None
    error: TranslationProviderError | None
    attempts: list[_BatchAttemptEvent]


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


def _language_pack_download_url(
    pack: CatalogLanguagePackRow,
    *,
    tenant_slug: str,
) -> str:
    if pack.public_url:
        return pack.public_url
    return (
        f"/api/store/{quote(tenant_slug, safe='')}/language-packages/"
        f"{quote(pack.target_locale, safe='')}/versions/{pack.version}"
    )


def _language_pack_response(
    pack: CatalogLanguagePackRow | None,
    *,
    tenant_slug: str,
) -> CatalogLanguagePackResponse | None:
    if pack is None:
        return None
    return CatalogLanguagePackResponse(
        source_locale=pack.source_locale,
        target_locale=pack.target_locale,
        version=pack.version,
        download_url=_language_pack_download_url(pack, tenant_slug=tenant_slug),
        content_sha256=pack.content_sha256,
        content_encoding=pack.content_encoding,
        byte_size=pack.byte_size,
        product_count=pack.product_count,
        sku_count=pack.sku_count,
        category_count=pack.category_count,
        source_cutoff_at=pack.source_cutoff_at,
        published_at=pack.published_at,
        last_full_translation_at=pack.last_full_translation_at,
    )


def _job_response(job: CatalogTranslationJobRow) -> CatalogTranslationJobResponse:
    if job.stage == "PUBLISHED" or job.status == "SUCCEEDED":
        progress = 100.0
    elif job.stage == "UPLOADING":
        progress = 97.0
    elif job.stage == "PACKAGING":
        progress = 93.0
    elif job.stage == "PREPARING":
        progress = 3.0
    elif job.total_skus == 0:
        progress = 8.0 if job.status == "RUNNING" else 0.0
    else:
        progress = min(
            90.0,
            round(5 + job.processed_skus / job.total_skus * 85, 1),
        )
    failures: list[CatalogTranslationFailure] = []
    for raw in job.failure_details or []:
        try:
            failures.append(CatalogTranslationFailure.model_validate(raw))
        except ValueError:
            continue
    remaining_skus = len(_remaining_sku_ids(job))
    if remaining_skus == 0 and job.processed_skus < job.total_skus:
        # Older failed jobs cleared their JSON checkpoint. The resume path
        # safely recomputes pending rows, so expose the truthful remaining
        # count instead of misleading users with zero.
        remaining_skus = job.total_skus - job.processed_skus
    batch_count = 0
    completed_batch_count = 0
    failed_batch_count = 0
    job_session = object_session(job)
    if job_session is not None:
        batch_statuses = list(
            job_session.scalars(
                select(CatalogTranslationBatchRow.status).where(
                    CatalogTranslationBatchRow.tenant_id == job.tenant_id,
                    CatalogTranslationBatchRow.job_id == job.id,
                )
            ).all()
        )
        batch_count = len(batch_statuses)
        completed_batch_count = sum(
            status == "SUCCEEDED" for status in batch_statuses
        )
        failed_batch_count = sum(
            status == "FAILED" for status in batch_statuses
        )
    return CatalogTranslationJobResponse(
        id=job.id,
        source_locale=job.source_locale,
        target_locale=job.target_locale,
        mode=job.mode,
        status=job.status,
        stage=job.stage,
        total_skus=job.total_skus,
        processed_skus=job.processed_skus,
        failed_skus=job.failed_skus,
        remaining_skus=remaining_skus,
        progress_percent=progress,
        current_sku_id=job.current_sku_id,
        current_sku_name=job.current_sku_name,
        failure_details=failures,
        error_message=job.error_message,
        package_version=job.package_version,
        package_published=job.package_published,
        package_byte_size=job.package_byte_size,
        source_cutoff_at=job.source_cutoff_at,
        pause_requested=(
            job.status in {"QUEUED", "RUNNING"}
            and job.pause_requested_at is not None
        ),
        pause_requested_at=job.pause_requested_at,
        paused_at=job.paused_at,
        resumable=job.status in {"PAUSED", "FAILED"},
        checkpoint_at=(
            job.updated_at
            if job.started_at is not None or job.processed_skus > 0
            else None
        ),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        batch_count=batch_count,
        completed_batch_count=completed_batch_count,
        failed_batch_count=failed_batch_count,
    )


def _as_uuid_list(values: list[str] | None) -> list[UUID]:
    result: list[UUID] = []
    for value in values or []:
        try:
            result.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return result


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((_as_utc(end) - _as_utc(start)).total_seconds() * 1000))


def _batch_attempt_response(
    attempt: CatalogTranslationBatchAttemptRow,
    *,
    include_skus: bool = True,
) -> CatalogTranslationBatchAttemptResponse:
    return CatalogTranslationBatchAttemptResponse(
        id=attempt.id,
        attempt_no=attempt.attempt_no,
        status=attempt.status,
        sku_ids=_as_uuid_list(attempt.sku_ids) if include_skus else [],
        sku_refs=(
            list(attempt.sku_refs or [])
            if include_skus
            else list(attempt.sku_refs or [])[:3]
        ),
        request_started_at=attempt.request_started_at,
        first_byte_at=attempt.first_byte_at,
        completed_at=attempt.completed_at,
        first_byte_latency_ms=_elapsed_ms(
            attempt.request_started_at,
            attempt.first_byte_at,
        ),
        response_time_ms=_elapsed_ms(
            attempt.request_started_at,
            attempt.completed_at,
        ),
        processed_skus=attempt.processed_skus,
        failed_skus=attempt.failed_skus,
        error_message=attempt.error_message,
    )


def _batch_response(
    batch: CatalogTranslationBatchRow,
    attempts: list[CatalogTranslationBatchAttemptRow] | None = None,
    *,
    include_skus: bool = True,
) -> CatalogTranslationBatchResponse:
    return CatalogTranslationBatchResponse(
        id=batch.id,
        sequence_no=batch.sequence_no,
        status=batch.status,
        sku_ids=_as_uuid_list(batch.sku_ids) if include_skus else [],
        sku_refs=(
            list(batch.sku_refs or [])
            if include_skus
            else list(batch.sku_refs or [])[:3]
        ),
        attempt_count=batch.attempt_count,
        total_skus=batch.total_skus,
        processed_skus=batch.processed_skus,
        failed_skus=batch.failed_skus,
        request_started_at=batch.request_started_at,
        first_byte_at=batch.first_byte_at,
        completed_at=batch.completed_at,
        response_time_ms=_elapsed_ms(
            batch.request_started_at,
            batch.completed_at,
        ),
        error_message=batch.error_message,
        attempts=[
            _batch_attempt_response(attempt, include_skus=include_skus)
            for attempt in (attempts or [])
        ],
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
            CatalogTranslationJobRow.status.in_(("QUEUED", "RUNNING", "PAUSED")),
        )
        .order_by(CatalogTranslationJobRow.created_at.desc())
        .limit(1)
    )


def _batch_sku_refs(batch: list[CatalogTranslationSource]) -> list[dict[str, str]]:
    return [
        {
            "id": str(source.sku_id),
            "code": source.sku_code,
            "name": source.name,
        }
        for source in batch
    ]


def _ensure_translation_batch_rows(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    batches: list[list[CatalogTranslationSource]],
) -> list[CatalogTranslationBatchRow]:
    """Create or reuse logical batch rows for a resumable job."""

    existing = list(
        session.scalars(
            select(CatalogTranslationBatchRow).where(
                CatalogTranslationBatchRow.tenant_id == job.tenant_id,
                CatalogTranslationBatchRow.job_id == job.id,
            )
        ).all()
    )
    by_sku_ids = {
        tuple(sorted(str(value) for value in row.sku_ids or [])): row
        for row in existing
        if row.status != "SUCCEEDED"
    }
    next_sequence = max((row.sequence_no for row in existing), default=0) + 1
    rows: list[CatalogTranslationBatchRow] = []
    for batch in batches:
        sku_ids = [str(source.sku_id) for source in batch]
        key = tuple(sorted(sku_ids))
        row = by_sku_ids.get(key)
        if row is None:
            row = CatalogTranslationBatchRow(
                tenant_id=job.tenant_id,
                job_id=job.id,
                sequence_no=next_sequence,
                status="QUEUED",
                sku_ids=sku_ids,
                sku_refs=_batch_sku_refs(batch),
                attempt_count=0,
                total_skus=len(batch),
                processed_skus=0,
                failed_skus=0,
            )
            next_sequence += 1
            session.add(row)
        else:
            row.status = "QUEUED"
            row.sku_ids = sku_ids
            row.sku_refs = _batch_sku_refs(batch)
            row.total_skus = len(batch)
            row.processed_skus = 0
            row.failed_skus = 0
            row.error_message = None
            row.request_started_at = None
            row.first_byte_at = None
            row.completed_at = None
        rows.append(row)
    session.flush()
    return rows


def _persist_batch_attempts(
    session: Session,
    *,
    job_batch: CatalogTranslationBatchRow,
    batch: list[CatalogTranslationSource],
    events: list[_BatchAttemptEvent],
) -> None:
    refs = _batch_sku_refs(batch)
    for event in events:
        session.add(
            CatalogTranslationBatchAttemptRow(
                tenant_id=job_batch.tenant_id,
                batch_id=job_batch.id,
                attempt_no=event.attempt_no,
                status=event.status,
                sku_ids=[str(source.sku_id) for source in batch],
                sku_refs=refs,
                request_started_at=event.request_started_at,
                first_byte_at=event.first_byte_at,
                completed_at=event.completed_at,
                processed_skus=event.processed_skus,
                failed_skus=event.failed_skus,
                error_message=event.error_message,
            )
        )
    if events:
        last = events[-1]
        job_batch.attempt_count += len(events)
        job_batch.request_started_at = events[0].request_started_at
        job_batch.first_byte_at = next(
            (event.first_byte_at for event in events if event.first_byte_at),
            None,
        )
        job_batch.completed_at = last.completed_at


def _reconcile_split_recovery_batches(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    remaining_ids: list[str],
) -> None:
    """Resolve parent batches that were automatically retried in smaller pieces.

    A recoverable provider error records a failed outbound attempt, but the
    logical batch is still in progress while its smaller child batches run.
    Once the recovery queue has drained, reflect the final SKU outcome on the
    parent row so operators do not see a stale FAILED/RUNNING batch after the
    job has actually recovered.
    """

    unresolved = set(remaining_ids)
    recovered_at = utcnow()
    recovering = list(
        session.scalars(
            select(CatalogTranslationBatchRow).where(
                CatalogTranslationBatchRow.tenant_id == job.tenant_id,
                CatalogTranslationBatchRow.job_id == job.id,
                CatalogTranslationBatchRow.status == "RUNNING",
            )
        ).all()
    )
    for batch in recovering:
        batch_ids = {str(value) for value in batch.sku_ids or []}
        failed_skus = len(batch_ids & unresolved)
        batch.processed_skus = max(0, batch.total_skus - failed_skus)
        batch.failed_skus = failed_skus
        batch.completed_at = recovered_at
        if failed_skus:
            batch.status = "FAILED"
            batch.error_message = (
                f"自动拆分重试后仍有 {failed_skus} 个 SKU 未完成。"
            )
        else:
            batch.status = "SUCCEEDED"
            batch.error_message = None


def _translate_batch_outcome(
    translator: TranslationProvider,
    batch: list[CatalogTranslationSource],
    *,
    source_locale: str,
    target_locale: str,
    max_retry_count: int,
    attempt_offset: int = 0,
) -> _BatchTranslationOutcome:
    events: list[_BatchAttemptEvent] = []
    base_delay = _positive_environment(
        "CATALOG_TRANSLATION_RETRY_BASE_SECONDS",
        2,
        maximum=30,
    )
    for attempt in range(max_retry_count + 1):
        started = utcnow()
        try:
            results = translate_catalog_sources(
                translator,
                batch,
                source_locale=source_locale,
                target_locale=target_locale,
            )
            # Providers currently expose a completed response rather than a
            # streaming body. Recording this boundary still gives operators
            # a stable first-byte/complete pair; streaming adapters can later
            # supply a more precise first_byte_at without changing the schema.
            first_byte = utcnow()
            completed = utcnow()
            events.append(
                _BatchAttemptEvent(
                    attempt_no=attempt_offset + attempt + 1,
                    request_started_at=started,
                    first_byte_at=first_byte,
                    completed_at=completed,
                    status="SUCCEEDED",
                    processed_skus=len(results),
                    failed_skus=max(0, len(batch) - len(results)),
                )
            )
            return _BatchTranslationOutcome(results, None, events)
        except TranslationProviderError as exc:
            completed = utcnow()
            events.append(
                _BatchAttemptEvent(
                    attempt_no=attempt_offset + attempt + 1,
                    request_started_at=started,
                    first_byte_at=completed,
                    completed_at=completed,
                    status="FAILED",
                    processed_skus=0,
                    failed_skus=len(batch),
                    error_message=str(exc),
                )
            )
            if (
                attempt >= max_retry_count
                or not _transient_translation_error(exc)
            ):
                return _BatchTranslationOutcome(None, exc, events)
            delay = min(base_delay * (2**attempt), 30)
            logger.warning(
                "catalog translation provider retry %s/%s in %ss: %s",
                attempt + 1,
                max_retry_count,
                delay,
                exc,
            )
            time.sleep(delay)
    raise AssertionError("translation retry loop did not return")


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
    if job is None or job.status == "PAUSED":
        return
    if _as_utc(job.updated_at) >= utcnow() - _stale_job_after:
        return
    if job.pause_requested_at is not None:
        job.status = "PAUSED"
        job.stage = "PAUSED"
        job.paused_at = utcnow()
        job.current_sku_id = None
        job.current_sku_name = None
        session.commit()
        return
    job.status = "PAUSED"
    job.stage = "PAUSED"
    job.failed_skus = max(0, job.total_skus - job.processed_skus)
    job.error_message = "翻译服务曾中断，已保留最近批次的断点，可继续翻译。"
    job.current_sku_id = None
    job.current_sku_name = None
    job.pause_requested_at = None
    job.paused_at = utcnow()
    job.completed_at = None
    session.commit()


def _all_rows(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[object]:
    return public_catalog_repository.list_all_public_catalog_rows(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
    )


def _pending_sources(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
    sources: list[CatalogTranslationSource],
    full_rebuild: bool,
) -> tuple[list[CatalogTranslationSource], int]:
    """Return sources whose content is missing or no longer matches.

    A translation provider/model is an implementation detail, not part of the
    catalog content identity.  Switching providers must not force a complete
    retranslation of unchanged SKU source text; operators can still request a
    full rebuild explicitly when they want to refresh wording.
    """

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


def list_translation_batches(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: UUID,
    include_skus: bool = True,
) -> list[CatalogTranslationBatchResponse]:
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
    batches = list(
        session.scalars(
            select(CatalogTranslationBatchRow)
            .where(
                CatalogTranslationBatchRow.tenant_id == tenant_id,
                CatalogTranslationBatchRow.job_id == job_id,
            )
            .order_by(CatalogTranslationBatchRow.sequence_no.asc())
        ).all()
    )
    if not batches:
        return []
    attempts = list(
        session.scalars(
            select(CatalogTranslationBatchAttemptRow)
            .where(
                CatalogTranslationBatchAttemptRow.tenant_id == tenant_id,
                CatalogTranslationBatchAttemptRow.batch_id.in_(
                    [batch.id for batch in batches]
                ),
            )
            .order_by(
                CatalogTranslationBatchAttemptRow.batch_id.asc(),
                CatalogTranslationBatchAttemptRow.attempt_no.asc(),
            )
        ).all()
    )
    attempts_by_batch: dict[UUID, list[CatalogTranslationBatchAttemptRow]] = {}
    for attempt in attempts:
        attempts_by_batch.setdefault(attempt.batch_id, []).append(attempt)
    return [
        _batch_response(
            batch,
            attempts_by_batch.get(batch.id, []),
            include_skus=include_skus,
        )
        for batch in batches
    ]


def _start_forced_translation_job(
    session: Session,
    *,
    context: RequestContext,
    target_locale: str,
    source_ids: list[UUID],
    reason: str,
    source_locale: str = _SOURCE_LOCALE,
) -> CatalogTranslationJobResponse:
    """Start a translation job for an explicit, stable set of SKU IDs.

    Product-level retranslation and failed-batch retry both use this path. The
    worker receives the IDs in the same order that the UI selected them, while
    each response is still persisted by ``sku_id`` so a provider returning
    markers out of order can never move a translation to another SKU.
    """

    ordered_ids = list(dict.fromkeys(source_ids))
    if not ordered_ids:
        raise ApplicationError(
            "CATALOG_TRANSLATION_PRODUCT_EMPTY",
            "该商品没有可翻译的公开 SKU。",
            kind="conflict",
        )
    _expire_stale_job(
        session,
        tenant_id=context.tenant_id,
        target_locale=target_locale,
    )
    existing = _active_job(
        session,
        tenant_id=context.tenant_id,
        target_locale=target_locale,
    )
    if existing is not None:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_CONFLICT",
            "当前语言已有翻译任务正在执行，请等待完成后再试。",
            kind="conflict",
        )
    try:
        translator = resolved_catalog_translator(
            session,
            environment_factory=configured_catalog_translator,
        )
    except TranslationProviderError as exc:
        raise ApplicationError(
            "CATALOG_TRANSLATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    if not language_package_storage_status().configured:
        raise ApplicationError(
            "CATALOG_LANGUAGE_PACKAGE_STORAGE_NOT_CONFIGURED",
            "语言包存储尚未配置，请联系平台管理员。",
        )

    job = CatalogTranslationJobRow(
        tenant_id=context.tenant_id,
        requested_by_membership_id=context.membership_id,
        requested_by_user_id=context.user_id,
        source_locale=source_locale,
        target_locale=target_locale,
        mode="INCREMENTAL",
        status="QUEUED",
        stage="QUEUED",
        total_skus=len(ordered_ids),
        processed_skus=0,
        failed_skus=0,
        provider=translator.identity.provider,
        provider_version=translator.identity.version,
        failure_details=[],
        remaining_sku_ids=[str(sku_id) for sku_id in ordered_ids],
        forced_sku_ids=[str(sku_id) for sku_id in ordered_ids],
        error_message=reason,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_CONFLICT",
            "当前语言已有翻译任务正在执行，请稍后再试。",
            kind="conflict",
        ) from exc
    try:
        _dispatch_translation_job(
            job_id=job.id,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except RuntimeError as exc:
        job.status = "FAILED"
        job.stage = "FAILED"
        job.failed_skus = len(ordered_ids)
        job.error_message = "翻译任务暂时无法启动，请稍后重试。"
        job.completed_at = utcnow()
        session.commit()
        raise ApplicationError(
            "CATALOG_TRANSLATION_DISPATCH_FAILED",
            job.error_message,
        ) from exc
    return _job_response(job)


def retry_translation_batch(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
    batch_id: UUID,
) -> CatalogTranslationJobResponse:
    _require(context.permissions, "product.edit")
    batch = session.scalar(
        select(CatalogTranslationBatchRow).where(
            CatalogTranslationBatchRow.tenant_id == context.tenant_id,
            CatalogTranslationBatchRow.id == batch_id,
            CatalogTranslationBatchRow.job_id == job_id,
        )
    )
    if batch is None:
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_NOT_FOUND",
            "翻译批次不存在。",
            kind="not_found",
        )
    if batch.status in {"QUEUED", "RUNNING"}:
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_BUSY",
            "该批次仍在请求中，完成后才可以重新请求。",
            kind="conflict",
        )
    source_ids = _as_uuid_list(batch.sku_ids)
    if not source_ids:
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_EMPTY",
            "该批次没有可重试的 SKU。",
            kind="conflict",
        )
    original_job = session.get(CatalogTranslationJobRow, job_id)
    if original_job is None:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_NOT_FOUND",
            "商品翻译任务不存在。",
            kind="not_found",
        )
    return _start_forced_translation_job(
        session,
        context=context,
        target_locale=original_job.target_locale,
        source_locale=original_job.source_locale,
        source_ids=source_ids,
        reason=f"重试翻译批次 #{batch.sequence_no}",
    )


def retry_translation_product(
    session: Session,
    *,
    context: RequestContext,
    product_id: UUID,
    request: CatalogTranslationProductRetryRequest,
) -> CatalogTranslationJobResponse:
    """Retranslate all customer-visible SKUs belonging to one product."""

    _require(context.permissions, "product.edit")
    rows = _all_rows(session, tenant_id=context.tenant_id)
    sources = [
        catalog_translation_source(row)
        for row in rows
        if row[2].id == product_id
    ]
    # Keep a deterministic order for batch history and provider prompts. The
    # actual save path remains keyed by SKU ID, so this is only an ordering
    # guarantee and never the source of correspondence.
    sources.sort(key=lambda source: (source.sku_code.casefold(), str(source.sku_id)))
    if not sources:
        raise ApplicationError(
            "CATALOG_TRANSLATION_PRODUCT_EMPTY",
            "该商品没有可翻译的公开 SKU。",
            kind="conflict",
        )
    product_name = next(
        (
            str(row[2].name or "").strip()
            for row in rows
            if row[2].id == product_id
        ),
        "",
    )
    return _start_forced_translation_job(
        session,
        context=context,
        target_locale=request.target_locale,
        source_ids=[source.sku_id for source in sources],
        reason=(
            f"重新翻译商品：{product_name}"
            if product_name
            else "重新翻译指定商品"
        ),
    )


def get_translation_status(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    target_locale: str = "en-US",
) -> CatalogTranslationStatusResponse:
    _require(permissions, "product.view")
    tenant = session.get(TenantRow, tenant_id)
    if tenant is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND",
            "商家工作区不存在。",
            kind="not_found",
        )
    configured = translation_provider_is_configured(
        session,
        environment_check=catalog_translation_is_configured,
    )
    if configured:
        try:
            resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            )
        except TranslationProviderError:
            configured = False

    rows = _all_rows(session, tenant_id=tenant_id)
    sources = [catalog_translation_source(row) for row in rows]
    pending, stale = _pending_sources(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
        sources=sources,
        full_rebuild=False,
    )
    valid_count = max(0, len(sources) - len(pending))
    pack = translation_repository.language_pack(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    current_source_digest = catalog_rows_source_digest(rows)
    storage_status = language_package_storage_status()
    package_outdated = bool(
        pack is None
        or pack.source_digest != current_source_digest
        or pack.storage_fingerprint != storage_status.fingerprint
    )
    return CatalogTranslationStatusResponse(
        source_locale=_SOURCE_LOCALE,
        target_locale=target_locale,
        provider_configured=configured,
        total_skus=len(sources),
        translated_skus=valid_count,
        stale_skus=stale,
        pending_skus=len(pending),
        package_outdated=package_outdated,
        package_storage_configured=storage_status.configured,
        available_locales=list(
            dict.fromkeys(
                [
                    _SOURCE_LOCALE,
                    *translation_repository.available_target_locales(
                        session,
                        tenant_id=tenant_id,
                    ),
                    *translation_repository.available_language_pack_locales(
                        session,
                        tenant_id=tenant_id,
                    ),
                ]
            )
        ),
        package=_language_pack_response(pack, tenant_slug=tenant.slug),
        latest_job=latest_translation_job(
            session,
            tenant_id=tenant_id,
            permissions=permissions,
            target_locale=target_locale,
        ),
    )


def _resolve_public_language_pack(
    session: Session,
    *,
    slug: str,
    target_locale: str,
) -> tuple[TenantRow, CatalogLanguagePackRow]:
    profile = public_catalog_repository.find_published_profile_by_slug(
        session,
        slug=slug.casefold().strip(),
    )
    if profile is None:
        raise ApplicationError(
            "STORE_NOT_FOUND",
            "Store was not found.",
            kind="not_found",
        )
    set_public_tenant_context(session, tenant_id=profile.tenant_id)
    tenant = public_catalog_repository.get_active_tenant(
        session,
        tenant_id=profile.tenant_id,
    )
    if tenant is None:
        raise ApplicationError(
            "STORE_NOT_FOUND",
            "Store was not found.",
            kind="not_found",
        )
    locale = normalize_storefront_locale(target_locale)
    source_locale = normalize_storefront_locale(tenant.default_locale) or _SOURCE_LOCALE
    enabled = effective_storefront_locales(
        profile.storefront_locales,
        source_locale=source_locale,
    )
    if locale is None or locale == source_locale or locale not in enabled:
        raise ApplicationError(
            "PUBLIC_LOCALE_DISABLED",
            "The requested storefront language is not enabled for this store.",
            kind="not_found",
        )
    pack = translation_repository.language_pack(
        session,
        tenant_id=tenant.id,
        target_locale=locale,
    )
    if pack is None:
        raise ApplicationError(
            "CATALOG_LANGUAGE_PACKAGE_NOT_FOUND",
            "The storefront language package is not available yet.",
            kind="not_found",
        )
    return tenant, pack


def public_language_pack(
    session: Session,
    *,
    slug: str,
    target_locale: str,
) -> CatalogLanguagePackResponse:
    tenant, pack = _resolve_public_language_pack(
        session,
        slug=slug,
        target_locale=target_locale,
    )
    response = _language_pack_response(pack, tenant_slug=tenant.slug)
    assert response is not None
    return response


def public_language_pack_content(
    session: Session,
    *,
    slug: str,
    target_locale: str,
    version: int,
) -> tuple[bytes, CatalogLanguagePackRow]:
    _tenant, pack = _resolve_public_language_pack(
        session,
        slug=slug,
        target_locale=target_locale,
    )
    if version != pack.version:
        raise ApplicationError(
            "CATALOG_LANGUAGE_PACKAGE_VERSION_NOT_FOUND",
            "The requested storefront language package version is no longer active.",
            kind="not_found",
        )
    try:
        content = configured_language_package_storage().get(pack.object_key)
    except Exception as exc:
        logger.warning(
            "public language package object unavailable for %s/%s/v%s: %s",
            slug,
            target_locale,
            version,
            type(exc).__name__,
        )
        raise ApplicationError(
            "CATALOG_LANGUAGE_PACKAGE_OBJECT_NOT_FOUND",
            "The storefront language package file is temporarily unavailable.",
            kind="unavailable",
        ) from exc
    return content, pack


def _safe_job_error(exc: Exception) -> str:
    if isinstance(exc, TranslationProviderError):
        return f"{str(exc).rstrip('。')}。已保存翻译断点，可稍后继续。"
    return "商品翻译任务执行中断，已保存翻译断点，可稍后继续。"


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


def _transient_translation_error(exc: TranslationProviderError) -> bool:
    message = str(exc).casefold()
    return any(token in message for token in _TRANSIENT_TRANSLATION_ERRORS)


def _remaining_sku_ids(job: CatalogTranslationJobRow) -> list[UUID]:
    values: list[UUID] = []
    for raw in job.remaining_sku_ids or []:
        try:
            values.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return values


def _forced_sku_ids(job: CatalogTranslationJobRow) -> list[UUID]:
    return _as_uuid_list(job.forced_sku_ids)


def _pause_at_safe_checkpoint(
    session: Session,
    job: CatalogTranslationJobRow,
) -> bool:
    """Acknowledge a cross-process pause request between provider batches."""

    session.refresh(
        job,
        attribute_names=("status", "pause_requested_at", "updated_at"),
    )
    if job.status == "PAUSED":
        return True
    if job.pause_requested_at is None:
        return False
    now = utcnow()
    job.status = "PAUSED"
    job.stage = "PAUSED"
    job.paused_at = now
    job.current_sku_id = None
    job.current_sku_name = None
    job.updated_at = now
    session.commit()
    return True


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
                CatalogTranslationJobRow.status == "QUEUED",
            ).with_for_update(skip_locked=True)
        )
        if job is None:
            return
        try:
            first_run = job.started_at is None
            job.status = "RUNNING"
            job.stage = "PREPARING"
            if first_run:
                job.started_at = utcnow()
            job.paused_at = None
            job.package_published = False
            job.error_message = None
            session.commit()

            if _pause_at_safe_checkpoint(session, job):
                return

            translator = resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            )
            rows = public_catalog_repository.list_all_public_catalog_rows(
                session,
                tenant_id=tenant_id,
                now=utcnow(),
            )
            sources = [catalog_translation_source(row) for row in rows]
            sources_by_id = {source.sku_id: source for source in sources}
            forced_ids = _forced_sku_ids(job)
            stored_remaining = _remaining_sku_ids(job)
            forced_resume = (
                not first_run
                and bool(forced_ids)
                and bool(stored_remaining)
            )
            preserve_progress = (
                not first_run
                and not forced_ids
                and (
                    bool(stored_remaining)
                    or job.processed_skus >= job.total_skus
                )
            )
            if forced_ids and not forced_resume:
                candidates = [
                    sources_by_id[sku_id]
                    for sku_id in forced_ids
                    if sku_id in sources_by_id
                ]
            elif forced_resume:
                candidates = [
                    sources_by_id[sku_id]
                    for sku_id in stored_remaining
                    if sku_id in sources_by_id
                ]
            elif preserve_progress and job.mode == "FULL_REBUILD":
                # An explicit full rebuild is allowed to resume its own
                # checkpoint even though the provider/model may have changed.
                candidates = [
                    sources_by_id[sku_id]
                    for sku_id in stored_remaining
                    if sku_id in sources_by_id
                ]
            elif preserve_progress:
                # Reconcile an incremental checkpoint against source hashes on
                # every resume.  Older jobs may have populated
                # ``remaining_sku_ids`` using the old provider-sensitive
                # rules; trusting that list would make a model switch keep
                # translating thousands of already-valid SKUs.
                candidates, _stale = _pending_sources(
                    session,
                    tenant_id=tenant_id,
                    target_locale=job.target_locale,
                    sources=sources,
                    full_rebuild=False,
                )
            else:
                candidates, _stale = _pending_sources(
                    session,
                    tenant_id=tenant_id,
                    target_locale=job.target_locale,
                    sources=sources,
                    full_rebuild=job.mode == "FULL_REBUILD",
                )
            storage = configured_language_package_storage()
            current_pack = translation_repository.language_pack(
                session,
                tenant_id=tenant_id,
                target_locale=job.target_locale,
            )
            previous_payload = load_language_pack_payload(storage, current_pack)
            job.provider = translator.identity.provider
            job.provider_version = translator.identity.version
            if preserve_progress or forced_resume:
                job.total_skus = job.processed_skus + len(candidates)
            else:
                job.total_skus = len(candidates)
                job.processed_skus = 0
                job.failed_skus = 0
                job.failure_details = []
            job.remaining_sku_ids = [str(source.sku_id) for source in candidates]
            job.stage = "TRANSLATING"
            session.commit()

            if _pause_at_safe_checkpoint(session, job):
                return

            batch_size, batch_characters = (
                resolved_catalog_translation_batch_limits(session)
            )
            max_retry_count = resolved_catalog_translation_retry_count(session)
            batches = translation_batches(
                candidates,
                max_items=batch_size,
                max_characters=batch_characters,
            )
            processed = job.processed_skus
            failures: list[dict[str, str]] = list(job.failure_details or [])
            remaining_ids = [str(source.sku_id) for source in candidates]
            batch_rows = _ensure_translation_batch_rows(
                session,
                job=job,
                batches=batches,
            )
            session.commit()
            pending_batches: list[tuple[list[CatalogTranslationSource], CatalogTranslationBatchRow]] = list(
                zip(batches, batch_rows, strict=True)
            )
            concurrency = resolved_catalog_translation_concurrency(session)
            # A one-SKU batch is already the smallest possible request. Keep
            # those checkpoints deterministic and avoid creating a burst of
            # tiny requests; normal 20–50 SKU batches still use the configured
            # concurrent request window.
            if batches and max(len(batch) for batch in batches) <= 1:
                concurrency = 1
            batch_index = 0
            with ThreadPoolExecutor(
                max_workers=concurrency,
                thread_name_prefix="catalog-translation-batch",
            ) as batch_executor:
                while batch_index < len(pending_batches):
                    if _pause_at_safe_checkpoint(session, job):
                        return
                    window = pending_batches[batch_index : batch_index + concurrency]
                    for batch, batch_row in window:
                        batch_row.status = "RUNNING"
                        batch_row.request_started_at = utcnow()
                        job.current_sku_id = batch[0].sku_id
                        job.current_sku_name = batch[0].name
                    job.updated_at = utcnow()
                    session.commit()

                    future_map: dict[
                        Future[_BatchTranslationOutcome],
                        tuple[list[CatalogTranslationSource], CatalogTranslationBatchRow],
                    ] = {
                        batch_executor.submit(
                            _translate_batch_outcome,
                            translator,
                            batch,
                            source_locale=job.source_locale,
                            target_locale=job.target_locale,
                            max_retry_count=max_retry_count,
                            attempt_offset=batch_row.attempt_count,
                        ): (batch, batch_row)
                        for batch, batch_row in window
                    }
                    split_batches: list[list[CatalogTranslationSource]] = []
                    stop_after_window = False
                    for future in as_completed(future_map):
                        batch, batch_row = future_map[future]
                        try:
                            outcome = future.result()
                        except Exception as exc:  # pragma: no cover - defensive
                            outcome = _BatchTranslationOutcome(
                                results=None,
                                error=TranslationProviderError(
                                    "translation batch request failed"
                                ),
                                attempts=[
                                    _BatchAttemptEvent(
                                        attempt_no=batch_row.attempt_count + 1,
                                        request_started_at=batch_row.request_started_at or utcnow(),
                                        first_byte_at=utcnow(),
                                        completed_at=utcnow(),
                                        status="FAILED",
                                        processed_skus=0,
                                        failed_skus=len(batch),
                                        error_message=type(exc).__name__,
                                    )
                                ],
                            )
                        _persist_batch_attempts(
                            session,
                            job_batch=batch_row,
                            batch=batch,
                            events=outcome.attempts,
                        )
                        if outcome.error is not None or outcome.results is None:
                            error = outcome.error or TranslationProviderError(
                                "translation batch request failed"
                            )
                            if error.recover_with_smaller_batches and len(batch) > 1:
                                # The provider request failed, but this logical
                                # batch has not failed yet: it is being retried
                                # automatically as smaller child batches. Keep
                                # it RUNNING until the child outcomes are known.
                                batch_row.status = "RUNNING"
                                batch_row.processed_skus = 0
                                batch_row.failed_skus = 0
                                batch_row.completed_at = None
                                batch_row.error_message = (
                                    "批次响应不完整，正在自动拆分重试。"
                                )
                                midpoint = max(1, len(batch) // 2)
                                split_batches.extend(
                                    [batch[:midpoint], batch[midpoint:]]
                                )
                            else:
                                batch_row.status = "FAILED"
                                batch_row.failed_skus = len(batch)
                                batch_row.error_message = str(error)
                                if len(failures) < _FAILURE_DETAIL_LIMIT:
                                    failures.append(_failure_detail(batch[0], str(error)))
                                job.failed_skus += len(batch)
                                # A non-recoverable provider error should not
                                # immediately hammer the upstream with all
                                # remaining batches. Keep those batches queued
                                # in the checkpoint so the operator can retry
                                # after correcting the provider or only retry
                                # the failed request from the history panel.
                                stop_after_window = True
                            job.failure_details = failures
                            job.remaining_sku_ids = [
                                str(source.sku_id)
                                for source in candidates
                                if str(source.sku_id) in remaining_ids
                            ]
                            job.updated_at = utcnow()
                            session.commit()
                            continue

                        source_by_id = {source.sku_id: source for source in batch}
                        translated_ids: set[UUID] = set()
                        for result in outcome.results:
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
                        processed += len(translated_ids)
                        translated_values = {str(sku_id) for sku_id in translated_ids}
                        remaining_ids = [
                            sku_id
                            for sku_id in remaining_ids
                            if sku_id not in translated_values
                        ]
                        batch_row.status = "SUCCEEDED" if failed_in_batch == 0 else "FAILED"
                        batch_row.processed_skus = len(translated_ids)
                        batch_row.failed_skus = failed_in_batch
                        if failed_in_batch:
                            job.failed_skus += failed_in_batch
                        job.processed_skus = processed
                        job.failure_details = failures
                        job.remaining_sku_ids = remaining_ids
                        job.updated_at = utcnow()
                        session.commit()

                    if split_batches:
                        split_rows = _ensure_translation_batch_rows(
                            session,
                            job=job,
                            batches=split_batches,
                        )
                        pending_batches.extend(
                            list(zip(split_batches, split_rows, strict=True))
                        )
                        session.commit()
                    batch_index += len(window)

                    if stop_after_window:
                        break

                    if _pause_at_safe_checkpoint(session, job):
                        return

            _reconcile_split_recovery_batches(
                session,
                job=job,
                remaining_ids=remaining_ids,
            )
            session.commit()

            if job.failed_skus:
                raise TranslationProviderError(
                    f"{job.failed_skus} 个 SKU 翻译失败，请重试增量翻译。"
                )

            if _pause_at_safe_checkpoint(session, job):
                return
            job.stage = "PACKAGING"
            job.current_sku_id = None
            job.current_sku_name = None
            job.updated_at = utcnow()
            session.commit()

            if _pause_at_safe_checkpoint(session, job):
                return

            sku_translations = translation_repository.translation_map(
                session,
                tenant_id=tenant_id,
                sku_ids=[source.sku_id for source in sources],
                target_locale=job.target_locale,
            )
            next_version = (current_pack.version if current_pack else 0) + 1
            build = build_catalog_language_pack(
                tenant_id=tenant_id,
                rows=rows,
                source_locale=job.source_locale,
                target_locale=job.target_locale,
                version=next_version,
                translator=translator,
                sku_translations=sku_translations,
                previous_payload=previous_payload,
                # A provider/model switch does not invalidate the published
                # package. Reuse entries by source hash and only translate
                # genuinely new or changed catalog content.
                reuse_previous=bool(current_pack),
                full_rebuild=job.mode == "FULL_REBUILD",
                force_rebuild_sku_ids=set(forced_ids),
            )
            object_key = language_pack_object_key(
                tenant_id=tenant_id,
                target_locale=job.target_locale,
                version=next_version,
                content_sha256=build.content_sha256,
            )
            job.stage = "UPLOADING"
            job.updated_at = utcnow()
            session.commit()
            stored = storage.put(build.compressed, object_key=object_key)
            published_at = utcnow()
            translation_repository.save_language_pack(
                session,
                tenant_id=tenant_id,
                source_locale=job.source_locale,
                target_locale=job.target_locale,
                version=next_version,
                object_key=stored.object_key,
                public_url=stored.public_url,
                content_sha256=build.content_sha256,
                source_digest=build.source_digest,
                storage_fingerprint=storage.status.fingerprint,
                byte_size=stored.byte_size,
                product_count=build.product_count,
                sku_count=build.sku_count,
                category_count=build.category_count,
                provider=translator.identity.provider,
                provider_version=translator.identity.version,
                source_cutoff_at=build.source_cutoff_at,
                published_at=published_at,
                full_rebuild=job.mode == "FULL_REBUILD",
            )
            job.status = "SUCCEEDED"
            job.stage = "PUBLISHED"
            job.package_version = next_version
            job.package_published = True
            job.package_byte_size = stored.byte_size
            job.source_cutoff_at = build.source_cutoff_at
            job.remaining_sku_ids = []
            job.forced_sku_ids = []
            job.pause_requested_at = None
            job.paused_at = None
            job.current_sku_id = None
            job.current_sku_name = None
            job.completed_at = published_at
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
            failed_job.stage = "FAILED"
            failed_job.failed_skus = max(
                failed_job.failed_skus,
                failed_job.total_skus - failed_job.processed_skus,
            )
            failed_job.error_message = _safe_job_error(exc)
            failed_job.current_sku_id = None
            failed_job.current_sku_name = None
            failed_job.pause_requested_at = None
            failed_job.paused_at = None
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


def _translation_job_tenant_ids(session: Session) -> tuple[UUID, ...]:
    """Discover tenants through the privileged read-only directory connection."""

    dialect = session.bind.dialect.name if session.bind is not None else "unknown"
    if dialect != "postgresql":
        return tuple(
            session.scalars(
                select(CatalogTranslationJobRow.tenant_id)
                .where(
                    CatalogTranslationJobRow.status.in_(("QUEUED", "RUNNING")),
                    CatalogTranslationJobRow.deleted_at.is_(None),
                )
                .distinct()
            ).all()
        )

    directory_url = os.getenv("TENANT_DIRECTORY_DATABASE_URL", "").strip()
    if not directory_url:
        logger.warning(
            "translation checkpoint recovery skipped: tenant directory is not configured"
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
            "translation checkpoint recovery could not read tenant directory"
        )
        return ()


def recover_interrupted_translation_jobs() -> int:
    """Convert process-owned unfinished jobs into resumable checkpoints.

    Translation workers currently run inside the API process. Any QUEUED or
    RUNNING row found during process startup therefore belongs to the previous
    process and cannot still be executing. Keeping it PAUSED avoids duplicate
    provider calls and lets the merchant continue from persisted translations.
    """

    with SessionLocal() as session:
        tenant_ids = _translation_job_tenant_ids(session)
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
                        select(CatalogTranslationJobRow).where(
                            CatalogTranslationJobRow.tenant_id == tenant_id,
                            CatalogTranslationJobRow.status.in_(("QUEUED", "RUNNING")),
                            CatalogTranslationJobRow.deleted_at.is_(None),
                        )
                    ).all()
                )
                if not interrupted:
                    session.rollback()
                    continue
                now = utcnow()
                for job in interrupted:
                    job.status = "PAUSED"
                    job.stage = "PAUSED"
                    job.pause_requested_at = None
                    job.paused_at = now
                    job.current_sku_id = None
                    job.current_sku_name = None
                    job.error_message = (
                        "服务重启前的翻译进度已保存，可从最近完成的批次继续。"
                    )
                    job.completed_at = None
                    job.updated_at = now
                session.commit()
                recovered += len(interrupted)
        except Exception:
            logger.exception(
                "translation checkpoint recovery failed for tenant %s",
                tenant_id,
            )
    return recovered


def _managed_job(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
    for_update: bool = False,
) -> CatalogTranslationJobRow:
    statement = (
        select(CatalogTranslationJobRow).where(
            CatalogTranslationJobRow.tenant_id == tenant_id,
            CatalogTranslationJobRow.id == job_id,
        )
    )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_NOT_FOUND",
            "商品翻译任务不存在。",
            kind="not_found",
        )
    return job


def pause_translation_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> CatalogTranslationJobResponse:
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
            "CATALOG_TRANSLATION_JOB_NOT_PAUSABLE",
            "当前翻译任务已经结束，无法暂停。",
            kind="conflict",
        )
    if job.stage in {"PACKAGING", "UPLOADING"}:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_NOT_PAUSABLE",
            "语言包正在整理或上传，当前阶段很快会完成，暂时无法暂停。",
            kind="conflict",
        )
    now = utcnow()
    job.pause_requested_at = now
    if job.status == "QUEUED":
        job.status = "PAUSED"
        job.stage = "PAUSED"
        job.paused_at = now
        job.current_sku_id = None
        job.current_sku_name = None
    session.commit()
    return _job_response(job)


def resume_translation_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> CatalogTranslationJobResponse:
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
            "CATALOG_TRANSLATION_JOB_NOT_RESUMABLE",
            "只有已暂停或中断的翻译任务可以继续。",
            kind="conflict",
        )
    existing = _active_job(
        session,
        tenant_id=context.tenant_id,
        target_locale=job.target_locale,
    )
    if existing is not None and existing.id != job.id:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_CONFLICT",
            "当前语言已有另一个翻译任务正在运行。",
            kind="conflict",
        )
    job.status = "QUEUED"
    job.stage = "QUEUED"
    job.pause_requested_at = None
    job.paused_at = None
    job.failed_skus = 0
    job.failure_details = []
    job.error_message = None
    job.completed_at = None
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_CONFLICT",
            "当前语言已有另一个翻译任务正在运行。",
            kind="conflict",
        ) from exc
    try:
        _dispatch_translation_job(
            job_id=job.id,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )
    except RuntimeError as exc:
        job.status = "PAUSED"
        job.stage = "PAUSED"
        job.paused_at = utcnow()
        session.commit()
        raise ApplicationError(
            "CATALOG_TRANSLATION_RESUME_FAILED",
            "翻译任务暂时无法继续，请稍后重试。",
        ) from exc
    return _job_response(job)


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
        translator = resolved_catalog_translator(
            session,
            environment_factory=configured_catalog_translator,
        )
    except TranslationProviderError as exc:
        raise ApplicationError(
            "CATALOG_TRANSLATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    storage_status = language_package_storage_status()
    if not storage_status.configured:
        raise ApplicationError(
            "CATALOG_LANGUAGE_PACKAGE_STORAGE_NOT_CONFIGURED",
            "语言包存储尚未配置，请联系平台管理员。",
        )

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

    rows = _all_rows(session, tenant_id=context.tenant_id)
    sources = [catalog_translation_source(row) for row in rows]
    candidates, _stale = _pending_sources(
        session,
        tenant_id=context.tenant_id,
        target_locale=request.target_locale,
        sources=sources,
        full_rebuild=request.mode == "FULL_REBUILD",
    )
    current_pack = translation_repository.language_pack(
        session,
        tenant_id=context.tenant_id,
        target_locale=request.target_locale,
    )
    current_digest = catalog_rows_source_digest(rows)
    package_current = bool(
        current_pack is not None
        and current_pack.source_digest == current_digest
        and current_pack.storage_fingerprint == storage_status.fingerprint
    )
    work_required = bool(
        request.mode == "FULL_REBUILD"
        or candidates
        or not package_current
    )
    now = utcnow()
    job = CatalogTranslationJobRow(
        tenant_id=context.tenant_id,
        requested_by_membership_id=context.membership_id,
        requested_by_user_id=context.user_id,
        source_locale=_SOURCE_LOCALE,
        target_locale=request.target_locale,
        mode=request.mode,
        status="QUEUED" if work_required else "SUCCEEDED",
        stage="QUEUED" if work_required else "PUBLISHED",
        total_skus=len(candidates),
        processed_skus=0,
        failed_skus=0,
        provider=translator.identity.provider,
        provider_version=translator.identity.version,
        failure_details=[],
        remaining_sku_ids=[str(source.sku_id) for source in candidates],
        package_version=current_pack.version if current_pack and not work_required else None,
        package_published=bool(current_pack and not work_required),
        package_byte_size=current_pack.byte_size if current_pack and not work_required else None,
        source_cutoff_at=current_pack.source_cutoff_at if current_pack and not work_required else None,
        completed_at=now if not work_required else None,
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

    if work_required:
        try:
            _dispatch_translation_job(
                job_id=job.id,
                organization_id=context.organization_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
            )
        except RuntimeError as exc:
            job.status = "FAILED"
            job.stage = "FAILED"
            job.failed_skus = len(candidates)
            job.error_message = "翻译任务暂时无法启动，请稍后重试。"
            job.completed_at = utcnow()
            session.commit()
            raise ApplicationError(
                "CATALOG_TRANSLATION_DISPATCH_FAILED",
                job.error_message,
            ) from exc
    return _job_response(job)
