from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

import psycopg
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from ..catalog_translation_models import (
    CatalogLanguagePackRow,
    CatalogSkuTranslationRow,
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
    catalog_translation_result_from_values,
    catalog_translation_value_is_complete,
    translate_catalog_sources,
    translation_batches,
)
from ..services.catalog_language_packages import (
    build_catalog_language_pack,
    catalog_language_pack_translatable_values,
    catalog_language_pack_translation_seed,
    catalog_rows_source_digest,
    language_pack_object_key,
    load_language_pack_payload,
)
from ..services.language_package_storage import (
    configured_language_package_storage,
    language_package_storage_status,
)
from ..services.translation import (
    TranslationIdentity,
    TranslationProvider,
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)
from ..services.translation_configuration import (
    catalog_translation_execution_mode,
    resolved_catalog_translation_batch_limits,
    resolved_catalog_translation_concurrency,
    resolved_catalog_translation_retry_count,
    resolved_catalog_translator,
    resolved_qwen_batch_configuration,
    translation_provider_is_configured,
)
from ..services.qwen_batch_translation import (
    QWEN_BATCH_TERMINAL_STATUSES,
    QwenBatchClient,
    QwenBatchItemFailure,
    QwenBatchParseResult,
    qwen_batch_translation_requests,
)
from ..services.translation_memory import (
    cached_translation_values,
    store_translation_values,
    translate_values_with_memory,
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
# Cloud Batch tasks spend most of their lifetime waiting on provider-side
# execution.  Keep them off the two real-time translation workers so operators
# can submit many target languages without serializing 24-hour cloud jobs.
_qwen_batch_executor = ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="catalog-qwen-batch",
)
_stale_job_after = timedelta(minutes=30)
_SOURCE_LOCALE = "zh-CN"
_FAILURE_DETAIL_LIMIT = 100
_ZERO_IDENTITY = UUID(int=0)
_LANGUAGE_PACK_FINALIZATION_KEY = "language_pack_finalization"
_QWEN_BATCH_PROGRESS_KEY = "qwen_batch_progress"
_QWEN_BATCH_MAX_RETRY_GENERATION = 3
_QWEN_BATCH_RETRY_LIMITS = (
    (20, 3_000),
    (5, 1_000),
    (1, 500),
)
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


class _CachedOnlyTranslationProvider:
    """Guard language-pack assembly against accidental real-time requests."""

    def __init__(self, identity: TranslationIdentity) -> None:
        self.identity = identity

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        raise TranslationProviderError(
            "Batch translation memory is incomplete; no real-time fallback was used"
        )


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


def _requested_job_execution_mode(
    session: Session,
    request: CatalogTranslationJobStartRequest,
) -> str:
    return request.execution_mode or catalog_translation_execution_mode(session)


def _supersede_paused_job_for_mode(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    execution_mode: str,
    explicitly_requested: bool,
) -> bool:
    if (
        not explicitly_requested
        or job.status != "PAUSED"
        or job.execution_mode == execution_mode
    ):
        return False
    # Preserve the transport and translation checkpoints while releasing the
    # one-active-job constraint for the deliberately selected execution mode.
    now = utcnow()
    job.status = "FAILED"
    job.stage = "FAILED"
    job.pause_requested_at = None
    job.completed_at = now
    job.error_message = "已切换翻译方式，原任务断点仍保留在历史记录中。"
    session.commit()
    return True


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


def _qwen_request_value_count(request: object) -> int:
    if not isinstance(request, dict):
        return 0
    values = request.get("values")
    return len(values) if isinstance(values, list) else 0


def _job_qwen_batch_counts(job: CatalogTranslationJobRow) -> tuple[int, int]:
    payload = job.batch_request_payload or {}
    progress = payload.get(_QWEN_BATCH_PROGRESS_KEY)
    progress = progress if isinstance(progress, dict) else {}
    requests = payload.get("requests")
    requests = requests if isinstance(requests, list) else []
    current_request_total = sum(
        _qwen_request_value_count(request) for request in requests
    )
    try:
        total = max(
            0,
            int(
                progress.get("total_values")
                or current_request_total
                or payload.get("value_count", 0)
            ),
        )
        processed = max(0, int(progress.get("processed_values", 0)))
    except (TypeError, ValueError):
        return 0, 0
    return total, min(processed, total)


def _job_qwen_batch_processed_skus(job: CatalogTranslationJobRow) -> int:
    payload = job.batch_request_payload or {}
    progress = payload.get(_QWEN_BATCH_PROGRESS_KEY)
    progress = progress if isinstance(progress, dict) else {}
    try:
        processed = max(0, int(progress.get("processed_skus", 0)))
    except (TypeError, ValueError):
        processed = 0
    return min(job.total_skus, max(job.processed_skus, processed))


def _qwen_batch_progress_fraction(
    *,
    translation_total: int,
    translation_processed: int,
    external_total_requests: int,
    external_completed_requests: int,
    external_failed_requests: int,
) -> float:
    """Combine exact imported progress with live provider request progress."""

    imported_fraction = (
        min(translation_processed, translation_total) / translation_total
        if translation_total > 0
        else 0.0
    )
    upstream_finished = min(
        max(0, external_total_requests),
        max(0, external_completed_requests) + max(0, external_failed_requests),
    )
    upstream_fraction = (
        upstream_finished / external_total_requests
        if external_total_requests > 0
        else 0.0
    )
    return min(1.0, max(imported_fraction, upstream_fraction))


def _job_response(job: CatalogTranslationJobRow) -> CatalogTranslationJobResponse:
    finalization_total, finalization_processed = _job_finalization_counts(job)
    translation_total, translation_processed = _job_qwen_batch_counts(job)
    translation_processed_skus = _job_qwen_batch_processed_skus(job)
    if job.stage == "PUBLISHED" or job.status == "SUCCEEDED":
        progress = 100.0
    elif job.stage == "UPLOADING":
        progress = 99.0
    elif job.stage == "PACKAGING":
        progress = 97.0
    elif job.stage == "PREPARING":
        progress = 3.0
    elif job.execution_mode == "QWEN_BATCH" and (
        translation_total > 0 or job.external_total_requests > 0
    ):
        batch_progress = _qwen_batch_progress_fraction(
            translation_total=translation_total,
            translation_processed=translation_processed,
            external_total_requests=job.external_total_requests,
            external_completed_requests=job.external_completed_requests,
            external_failed_requests=job.external_failed_requests,
        )
        progress = min(
            90.0,
            round(8 + batch_progress * 82, 1),
        )
    elif finalization_total > 0 and job.processed_skus >= job.total_skus:
        progress = round(
            90.0
            + min(finalization_processed, finalization_total)
            / finalization_total
            * 6.0,
            1,
        )
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
        batch_count, completed_batch_count, failed_batch_count = (
            int(value or 0)
            for value in job_session.execute(
                select(
                    func.count(CatalogTranslationBatchRow.id),
                    func.sum(
                        case(
                            (CatalogTranslationBatchRow.status == "SUCCEEDED", 1),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (CatalogTranslationBatchRow.status == "FAILED", 1),
                            else_=0,
                        )
                    ),
                ).where(
                    CatalogTranslationBatchRow.tenant_id == job.tenant_id,
                    CatalogTranslationBatchRow.job_id == job.id,
                )
            ).one()
        )
    return CatalogTranslationJobResponse(
        id=job.id,
        source_locale=job.source_locale,
        target_locale=job.target_locale,
        mode=job.mode,
        execution_mode=job.execution_mode,
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
        external_batch_id=job.external_batch_id,
        external_batch_status=job.external_batch_status,
        external_total_requests=job.external_total_requests,
        external_completed_requests=job.external_completed_requests,
        external_failed_requests=job.external_failed_requests,
        translation_total_values=translation_total,
        translation_processed_values=translation_processed,
        translation_processed_skus=translation_processed_skus,
        finalization_total_values=finalization_total,
        finalization_processed_values=finalization_processed,
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
    refs = list(batch.sku_refs or [])
    is_text_batch = bool(
        not batch.sku_ids
        and refs
        and refs[0].get("kind") == "TEXT"
    )
    return CatalogTranslationBatchResponse(
        id=batch.id,
        sequence_no=batch.sequence_no,
        status=batch.status,
        item_kind="TEXT" if is_text_batch else "SKU",
        request_id=(refs[0].get("id") if is_text_batch else None),
        source_locale=(refs[0].get("code") if is_text_batch else None),
        sku_ids=_as_uuid_list(batch.sku_ids) if include_skus else [],
        sku_refs=(
            refs
            if include_skus
            else refs[:3]
        ),
        attempt_count=batch.attempt_count,
        total_skus=batch.total_skus,
        processed_skus=batch.processed_skus,
        failed_skus=batch.failed_skus,
        total_items=batch.total_skus,
        processed_items=batch.processed_skus,
        failed_items=batch.failed_skus,
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


def _qwen_request_refs(request: dict[str, object]) -> list[dict[str, str]]:
    custom_id = request.get("custom_id")
    source_locale = request.get("source_locale")
    values = request.get("values")
    if (
        not isinstance(custom_id, str)
        or not isinstance(source_locale, str)
        or not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise TranslationProviderError(
            "Qwen Batch translation snapshot is invalid"
        )
    return [
        {
            "id": custom_id,
            "code": source_locale,
            "name": value,
            "kind": "TEXT",
        }
        for value in values
    ]


def _qwen_batch_row_id(request: dict[str, object]) -> UUID | None:
    raw = request.get("batch_row_id")
    try:
        return UUID(str(raw)) if raw else None
    except (TypeError, ValueError):
        return None


def _ensure_qwen_batch_rows(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    requests: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, CatalogTranslationBatchRow]]:
    """Attach each JSONL request to the existing operator batch history."""

    existing = list(
        session.scalars(
            select(CatalogTranslationBatchRow).where(
                CatalogTranslationBatchRow.tenant_id == job.tenant_id,
                CatalogTranslationBatchRow.job_id == job.id,
            )
        ).all()
    )
    by_id = {row.id: row for row in existing}
    by_request_id: dict[str, CatalogTranslationBatchRow] = {}
    for row in existing:
        refs = list(row.sku_refs or [])
        if (
            not row.sku_ids
            and refs
            and refs[0].get("kind") == "TEXT"
            and refs[0].get("id")
            and row.status != "SUCCEEDED"
        ):
            by_request_id[str(refs[0]["id"])] = row
    next_sequence = max((row.sequence_no for row in existing), default=0) + 1
    prepared: list[tuple[dict[str, object], CatalogTranslationBatchRow]] = []
    for raw_request in requests:
        request = dict(raw_request)
        refs = _qwen_request_refs(request)
        custom_id = str(request["custom_id"])
        row_id = _qwen_batch_row_id(request)
        row = by_id.get(row_id) if row_id is not None else None
        if row is None:
            row = by_request_id.get(custom_id)
        if row is None:
            row = CatalogTranslationBatchRow(
                tenant_id=job.tenant_id,
                job_id=job.id,
                sequence_no=next_sequence,
                status="QUEUED",
                sku_ids=[],
                sku_refs=refs,
                attempt_count=0,
                total_skus=len(refs),
                processed_skus=0,
                failed_skus=0,
            )
            next_sequence += 1
            session.add(row)
        elif bool(request.get("force_retry")) or row.status != "SUCCEEDED":
            row.status = "QUEUED"
            row.sku_ids = []
            row.sku_refs = refs
            row.total_skus = len(refs)
            row.processed_skus = 0
            row.failed_skus = 0
            row.error_message = None
            row.request_started_at = None
            row.first_byte_at = None
            row.completed_at = None
        prepared.append((request, row))
    session.flush()

    updated: list[dict[str, object]] = []
    rows_by_request: dict[str, CatalogTranslationBatchRow] = {}
    for request, row in prepared:
        request["batch_row_id"] = str(row.id)
        custom_id = str(request["custom_id"])
        updated.append(request)
        rows_by_request[custom_id] = row
    return updated, rows_by_request


def _mark_qwen_batch_rows_running(
    rows_by_request: dict[str, CatalogTranslationBatchRow],
) -> None:
    started = utcnow()
    for row in rows_by_request.values():
        if row.status == "SUCCEEDED":
            continue
        row.status = "RUNNING"
        row.request_started_at = started
        row.first_byte_at = None
        row.completed_at = None
        row.processed_skus = 0
        row.failed_skus = 0
        row.error_message = None


def _record_qwen_batch_parse_result(
    session: Session,
    *,
    requests: list[dict[str, object]],
    rows_by_request: dict[str, CatalogTranslationBatchRow],
    result: QwenBatchParseResult,
) -> None:
    failures = {failure.custom_id: failure for failure in result.failures}
    successful = set(result.successful_request_ids)
    completed_at = utcnow()
    for request in requests:
        custom_id = str(request.get("custom_id", ""))
        row = rows_by_request.get(custom_id)
        if row is None:
            continue
        values = request.get("values")
        total = len(values) if isinstance(values, list) else 0
        failure = failures.get(custom_id)
        succeeded = custom_id in successful and failure is None
        error_message = failure.error_message if failure else None
        started_at = row.request_started_at or completed_at
        attempt_no = row.attempt_count + 1
        session.add(
            CatalogTranslationBatchAttemptRow(
                tenant_id=row.tenant_id,
                batch_id=row.id,
                attempt_no=attempt_no,
                status="SUCCEEDED" if succeeded else "FAILED",
                sku_ids=[],
                sku_refs=list(row.sku_refs or [])[:3],
                request_started_at=started_at,
                first_byte_at=completed_at,
                completed_at=completed_at,
                processed_skus=total if succeeded else 0,
                failed_skus=0 if succeeded else total,
                error_message=error_message,
            )
        )
        row.attempt_count = attempt_no
        row.first_byte_at = completed_at
        row.completed_at = completed_at
        row.processed_skus = total if succeeded else 0
        row.failed_skus = 0 if succeeded else total
        row.status = "SUCCEEDED" if succeeded else "FAILED"
        row.error_message = error_message


def _record_qwen_batch_transport_failure(
    session: Session,
    *,
    requests: list[dict[str, object]],
    rows_by_request: dict[str, CatalogTranslationBatchRow],
    error_message: str,
) -> None:
    result = QwenBatchParseResult(
        translations_by_locale={},
        successful_request_ids=(),
        failures=tuple(
            QwenBatchItemFailure(
                custom_id=str(request.get("custom_id", "")),
                request=dict(request),
                error_message=error_message,
            )
            for request in requests
        ),
    )
    _record_qwen_batch_parse_result(
        session,
        requests=requests,
        rows_by_request=rows_by_request,
        result=result,
    )


def _qwen_retry_requests(
    failures: tuple[QwenBatchItemFailure, ...],
    *,
    job_id: UUID,
    generation: int,
) -> tuple[list[dict[str, object]], set[UUID]]:
    limit_index = min(max(generation - 1, 0), len(_QWEN_BATCH_RETRY_LIMITS) - 1)
    max_items, max_characters = _QWEN_BATCH_RETRY_LIMITS[limit_index]
    requests: list[dict[str, object]] = []
    split_parent_ids: set[UUID] = set()
    sequence = 0
    for failure in failures:
        source_locale = failure.request.get("source_locale")
        values = failure.request.get("values")
        if not isinstance(source_locale, str) or not isinstance(values, list):
            continue
        generated = qwen_batch_translation_requests(
            {source_locale: [str(value) for value in values]},
            job_id=job_id,
            max_items=max_items,
            max_characters=max_characters,
            generation=generation,
            sequence_start=sequence,
        )
        sequence += len(generated)
        parent_id = _qwen_batch_row_id(failure.request)
        if (
            parent_id is not None
            and len(generated) == 1
            and generated[0].get("values") == values
        ):
            generated[0]["batch_row_id"] = str(parent_id)
            generated[0]["force_retry"] = True
        elif parent_id is not None:
            split_parent_ids.add(parent_id)
            for request in generated:
                request["parent_batch_id"] = str(parent_id)
        requests.extend(generated)
    return requests, split_parent_ids


def _mark_qwen_split_parents(
    session: Session,
    *,
    tenant_id: UUID,
    parent_ids: set[UUID],
) -> None:
    if not parent_ids:
        return
    parents = list(
        session.scalars(
            select(CatalogTranslationBatchRow).where(
                CatalogTranslationBatchRow.tenant_id == tenant_id,
                CatalogTranslationBatchRow.id.in_(parent_ids),
            )
        ).all()
    )
    for parent in parents:
        parent.status = "CANCELLED"
        parent.error_message = "响应不完整，已拆分为更小批次继续重试。"


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


def _status_rows(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[object]:
    return public_catalog_repository.list_all_public_catalog_translation_rows(
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
    limit: int | None = None,
    include_failed: bool = True,
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
    batch_statement = select(CatalogTranslationBatchRow).where(
        CatalogTranslationBatchRow.tenant_id == tenant_id,
        CatalogTranslationBatchRow.job_id == job_id,
    )
    if limit is None:
        batches = list(
            session.scalars(
                batch_statement.order_by(CatalogTranslationBatchRow.sequence_no.asc())
            ).all()
        )
    else:
        recent = list(
            session.scalars(
                batch_statement
                .order_by(CatalogTranslationBatchRow.sequence_no.desc())
                .limit(limit)
            ).all()
        )
        recent.reverse()
        if include_failed:
            recent_ids = [batch.id for batch in recent]
            failed_statement = batch_statement.where(
                CatalogTranslationBatchRow.status == "FAILED"
            )
            if recent_ids:
                failed_statement = failed_statement.where(
                    CatalogTranslationBatchRow.id.not_in(recent_ids)
                )
            failed = list(
                session.scalars(
                    failed_statement.order_by(
                        CatalogTranslationBatchRow.sequence_no.asc()
                    )
                ).all()
            )
            batches = [*failed, *recent]
        else:
            batches = recent
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
    execution_mode = catalog_translation_execution_mode(session)
    try:
        if execution_mode == "QWEN_BATCH":
            identity = resolved_qwen_batch_configuration(session).identity
        else:
            identity = resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            ).identity
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
        execution_mode=execution_mode,
        status="QUEUED",
        stage="QUEUED",
        total_skus=len(ordered_ids),
        processed_skus=0,
        failed_skus=0,
        provider=identity.provider,
        provider_version=identity.version,
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


def _is_qwen_text_batch(batch: CatalogTranslationBatchRow) -> bool:
    refs = list(batch.sku_refs or [])
    return bool(
        not batch.sku_ids
        and refs
        and refs[0].get("kind") == "TEXT"
    )


def _retry_qwen_text_batch(
    session: Session,
    *,
    context: RequestContext,
    job: CatalogTranslationJobRow,
    batch: CatalogTranslationBatchRow,
) -> CatalogTranslationJobResponse:
    if job.execution_mode != "QWEN_BATCH" or job.status != "FAILED":
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_NOT_RETRYABLE",
            "只有中断的 Qwen Batch 任务可以单独重试失败批次。",
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
    refs = [
        ref
        for ref in list(batch.sku_refs or [])
        if ref.get("kind") == "TEXT" and ref.get("name")
    ]
    source_locales = {
        str(ref.get("code")) for ref in refs if ref.get("code")
    }
    values = list(dict.fromkeys(str(ref["name"]) for ref in refs))
    if len(source_locales) != 1 or not values:
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_EMPTY",
            "该批次没有可重试的翻译字段。",
            kind="conflict",
        )
    try:
        configuration = resolved_qwen_batch_configuration(session)
        client = QwenBatchClient(
            configuration,
            production=os.getenv("APP_ENV", "development").strip().lower()
            in {"production", "staging"},
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

    snapshot = dict(job.batch_request_payload or {})
    previous_generation = _qwen_retry_generation(snapshot)
    generation = previous_generation + 1
    failure = QwenBatchItemFailure(
        custom_id=(refs[0].get("id") or f"batch-{batch.id}"),
        request={
            "custom_id": refs[0].get("id") or f"batch-{batch.id}",
            "source_locale": next(iter(source_locales)),
            "values": values,
            "batch_row_id": str(batch.id),
        },
        error_message=batch.error_message or "手动重试失败批次",
    )
    retry_requests, split_parent_ids = _qwen_retry_requests(
        (failure,),
        job_id=job.id,
        generation=generation,
    )
    if not retry_requests:
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_EMPTY",
            "该批次没有可重试的翻译字段。",
            kind="conflict",
        )
    _mark_qwen_split_parents(
        session,
        tenant_id=job.tenant_id,
        parent_ids=split_parent_ids,
    )
    retry_requests, _rows_by_request = _ensure_qwen_batch_rows(
        session,
        job=job,
        requests=retry_requests,
    )
    rows = public_catalog_repository.list_all_public_catalog_rows(
        session,
        tenant_id=job.tenant_id,
        now=utcnow(),
    )
    sources = [catalog_translation_source(row) for row in rows]
    current_catalog_digest = catalog_rows_source_digest(rows)
    catalog_changed = snapshot.get("catalog_digest") != current_catalog_digest
    snapshot["schema_version"] = 2
    snapshot["catalog_digest"] = current_catalog_digest
    snapshot["requests"] = retry_requests
    if catalog_changed or not isinstance(
        snapshot.get("candidate_source_hashes"),
        dict,
    ):
        snapshot["candidate_source_hashes"] = {
            str(source.sku_id): source.source_hash for source in sources
        }
        snapshot["processed_skus_before_batch"] = 0
        job.total_skus = len(sources)
        job.processed_skus = 0
        job.remaining_sku_ids = [str(source.sku_id) for source in sources]
    job.batch_request_payload = snapshot
    translation_total, translation_processed = _job_qwen_batch_counts(job)
    _save_qwen_batch_progress(
        job,
        total=max(translation_total, translation_processed + len(values)),
        processed=translation_processed,
        retry_generation=generation,
    )
    stale_file_ids = _clear_qwen_batch_checkpoint(
        job,
        clear_payload=False,
    )
    job.status = "QUEUED"
    job.stage = "QUEUED"
    job.pause_requested_at = None
    job.paused_at = None
    job.failed_skus = 0
    job.failure_details = []
    job.error_message = None
    job.completed_at = None
    job.external_total_requests = len(retry_requests)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_CONFLICT",
            "当前语言已有另一个翻译任务正在运行。",
            kind="conflict",
        ) from exc
    _delete_qwen_batch_files(client, stale_file_ids)
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
        job.error_message = "翻译批次暂时无法重新提交，请稍后再试。"
        job.completed_at = utcnow()
        session.commit()
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_RETRY_FAILED",
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
    original_job = session.get(CatalogTranslationJobRow, job_id)
    if original_job is None:
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_NOT_FOUND",
            "商品翻译任务不存在。",
            kind="not_found",
        )
    if _is_qwen_text_batch(batch):
        return _retry_qwen_text_batch(
            session,
            context=context,
            job=original_job,
            batch=batch,
        )
    source_ids = _as_uuid_list(batch.sku_ids)
    if not source_ids:
        raise ApplicationError(
            "CATALOG_TRANSLATION_BATCH_EMPTY",
            "该批次没有可重试的 SKU。",
            kind="conflict",
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
    include_latest_job: bool = True,
) -> CatalogTranslationStatusResponse:
    _require(permissions, "product.view")
    tenant = session.get(TenantRow, tenant_id)
    if tenant is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND",
            "商家工作区不存在。",
            kind="not_found",
        )
    execution_mode = catalog_translation_execution_mode(session)
    if execution_mode == "QWEN_BATCH":
        try:
            resolved_qwen_batch_configuration(session)
            configured = True
        except TranslationProviderError:
            configured = False
    else:
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

    pack = translation_repository.language_pack(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    storage_status = language_package_storage_status()
    translation_count = translation_repository.count_translations(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    if pack is None and translation_count == 0:
        # A language that only has a Qwen text-memory checkpoint has no
        # materialized per-SKU rows yet. A count query is exact here and avoids
        # loading and hashing the full catalog merely to prove every SKU is
        # pending; live Batch progress comes from /jobs/latest.
        total_skus = public_catalog_repository.count_public_catalog_rows(
            session,
            tenant_id=tenant_id,
            now=utcnow(),
            query="",
            category=None,
            tags=set(),
        )
        valid_count = 0
        pending_count = total_skus
        stale = 0
        package_outdated = True
    else:
        rows = _status_rows(session, tenant_id=tenant_id)
        sources = [catalog_translation_source(row) for row in rows]
        pending, stale = _pending_sources(
            session,
            tenant_id=tenant_id,
            target_locale=target_locale,
            sources=sources,
            full_rebuild=False,
        )
        total_skus = len(sources)
        pending_count = len(pending)
        valid_count = max(0, total_skus - pending_count)
        package_outdated = bool(
            pack is None
            or pack.source_digest != catalog_rows_source_digest(rows)
            or pack.storage_fingerprint != storage_status.fingerprint
        )
    return CatalogTranslationStatusResponse(
        source_locale=_SOURCE_LOCALE,
        target_locale=target_locale,
        provider_configured=configured,
        total_skus=total_skus,
        translated_skus=valid_count,
        stale_skus=stale,
        pending_skus=pending_count,
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
        latest_job=(
            latest_translation_job(
                session,
                tenant_id=tenant_id,
                permissions=permissions,
                target_locale=target_locale,
            )
            if include_latest_job
            else None
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
        message = str(exc).rstrip("。")
        prefix = "language package translation left "
        suffix = " fields incomplete"
        if message.startswith(prefix) and message.endswith(suffix):
            count = message[len(prefix) : -len(suffix)]
            if count.isdigit():
                message = f"语言包仍有 {count} 个字段未完成翻译"
        return f"{message}。已保存翻译断点，可稍后继续。"
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


def _job_finalization_counts(job: CatalogTranslationJobRow) -> tuple[int, int]:
    payload = job.batch_request_payload or {}
    checkpoint = payload.get(_LANGUAGE_PACK_FINALIZATION_KEY)
    if not isinstance(checkpoint, dict):
        return 0, 0
    try:
        total = max(0, int(checkpoint.get("total_values", 0)))
        processed = max(0, int(checkpoint.get("processed_values", 0)))
    except (TypeError, ValueError):
        return 0, 0
    return total, min(processed, total)


def _save_job_finalization_counts(
    job: CatalogTranslationJobRow,
    *,
    total: int,
    processed: int,
) -> None:
    payload = dict(job.batch_request_payload or {})
    payload[_LANGUAGE_PACK_FINALIZATION_KEY] = {
        "total_values": max(0, total),
        "processed_values": max(0, min(processed, total)),
    }
    # Assign a new object so SQLAlchemy reliably detects the JSON update on
    # both PostgreSQL and SQLite.
    job.batch_request_payload = payload


def _save_qwen_batch_progress(
    job: CatalogTranslationJobRow,
    *,
    total: int,
    processed: int,
    imported_batch_id: str | None = None,
    retry_generation: int | None = None,
    processed_skus: int | None = None,
) -> dict[str, object]:
    payload = dict(job.batch_request_payload or {})
    previous = payload.get(_QWEN_BATCH_PROGRESS_KEY)
    previous = previous if isinstance(previous, dict) else {}
    raw_imported = previous.get("imported_batch_ids", [])
    raw_imported = raw_imported if isinstance(raw_imported, list) else []
    imported = [
        str(value)
        for value in raw_imported
        if isinstance(value, str) and value.strip()
    ]
    if imported_batch_id and imported_batch_id not in imported:
        imported.append(imported_batch_id)
    try:
        generation = max(0, int(previous.get("retry_generation", 0)))
    except (TypeError, ValueError):
        generation = 0
    if retry_generation is not None:
        generation = max(0, retry_generation)
    try:
        completed_skus = max(0, int(previous.get("processed_skus", 0)))
    except (TypeError, ValueError):
        completed_skus = 0
    if processed_skus is not None:
        completed_skus = max(0, processed_skus)
    payload[_QWEN_BATCH_PROGRESS_KEY] = {
        "total_values": max(0, total),
        "processed_values": max(0, min(processed, total)),
        "retry_generation": generation,
        "processed_skus": completed_skus,
        "imported_batch_ids": imported,
    }
    job.batch_request_payload = payload
    return payload


def _qwen_imported_batch_ids(snapshot: dict[str, object]) -> set[str]:
    progress = snapshot.get(_QWEN_BATCH_PROGRESS_KEY)
    progress = progress if isinstance(progress, dict) else {}
    values = progress.get("imported_batch_ids")
    return {
        value
        for value in values
        if isinstance(value, str) and value.strip()
    } if isinstance(values, list) else set()


def _qwen_retry_generation(snapshot: dict[str, object]) -> int:
    progress = snapshot.get(_QWEN_BATCH_PROGRESS_KEY)
    progress = progress if isinstance(progress, dict) else {}
    try:
        return max(0, int(progress.get("retry_generation", 0)))
    except (TypeError, ValueError):
        return 0


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


def _catalog_value_source_locale(value: str) -> str:
    return (
        _SOURCE_LOCALE
        if any("\u3400" <= character <= "\u9fff" for character in value)
        else "en-US"
    )


def _batch_translation_availability(
    *,
    tenant_id: UUID,
    target_locale: str,
    identity: TranslationIdentity,
    values: list[str],
    seed: dict[str, str],
    force_refresh_values: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    forced = force_refresh_values or set()
    available: dict[str, str] = {}
    pending_by_locale: dict[str, list[str]] = {}
    for value in values:
        source_locale = _catalog_value_source_locale(value)
        if source_locale == target_locale:
            available[value] = value
            continue
        seeded = None if value in forced else seed.get(value)
        if seeded and catalog_translation_value_is_complete(
            value,
            seeded,
            source_locale=source_locale,
            target_locale=target_locale,
        ):
            available[value] = seeded
            continue
        pending_by_locale.setdefault(source_locale, []).append(value)

    missing_by_locale: dict[str, list[str]] = {}
    for source_locale, group in pending_by_locale.items():
        cache_candidates = [value for value in group if value not in forced]
        cached = cached_translation_values(
            tenant_id=tenant_id,
            values=cache_candidates,
            source_locale=source_locale,
            target_locale=target_locale,
            provider=identity.provider,
            provider_version=identity.version,
        )
        available.update(cached)
        missing = [value for value in group if value not in available]
        if missing:
            missing_by_locale[source_locale] = missing
    return available, missing_by_locale


def _qwen_complete_candidate_sku_count(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    identity: TranslationIdentity,
    rows: list[object],
    snapshot: dict[str, object],
    storage: object,
) -> int:
    """Count SKUs whose required text is already safe to materialize."""

    if snapshot.get("catalog_digest") != catalog_rows_source_digest(rows):
        return 0
    sources = [catalog_translation_source(row) for row in rows]
    source_by_id = {str(source.sku_id): source for source in sources}
    current_pack = translation_repository.language_pack(
        session,
        tenant_id=job.tenant_id,
        target_locale=job.target_locale,
    )
    previous_payload = load_language_pack_payload(storage, current_pack)
    sku_translations = translation_repository.translation_map(
        session,
        tenant_id=job.tenant_id,
        sku_ids=[source.sku_id for source in sources],
        target_locale=job.target_locale,
    )
    values = catalog_language_pack_translatable_values(rows)
    seed = (
        {}
        if job.mode == "FULL_REBUILD"
        else catalog_language_pack_translation_seed(
            rows,
            sku_translations=sku_translations,
            previous_payload=previous_payload,
            reuse_previous=bool(current_pack),
        )
    )
    translations, _missing = _batch_translation_availability(
        tenant_id=job.tenant_id,
        target_locale=job.target_locale,
        identity=identity,
        values=values,
        seed=seed,
    )
    candidate_hashes = snapshot.get("candidate_source_hashes")
    candidate_hashes = (
        candidate_hashes if isinstance(candidate_hashes, dict) else {}
    )
    completed = 0
    for sku_id, source_hash in candidate_hashes.items():
        source = source_by_id.get(str(sku_id))
        if source is None or source.source_hash != source_hash:
            continue
        try:
            catalog_translation_result_from_values(
                source,
                translations,
                source_locale=job.source_locale,
                target_locale=job.target_locale,
            )
        except TranslationProviderError:
            continue
        completed += 1
    return min(job.total_skus, completed)


def _translation_value_checkpoint_batches(
    values: list[str],
    *,
    max_items: int,
    max_characters: int,
) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    current_characters = 0
    for value in values:
        if current and (
            len(current) >= max_items
            or current_characters + len(value) > max_characters
        ):
            batches.append(current)
            current = []
            current_characters = 0
        current.append(value)
        current_characters += len(value)
    if current:
        batches.append(current)
    return batches


def _prepare_realtime_language_pack_values(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    translator: TranslationProvider,
    rows: list[object],
    sku_translations: dict[UUID, CatalogSkuTranslationRow],
    previous_payload: dict[str, object] | None,
    reuse_previous: bool,
) -> bool:
    """Finish non-SKU package fields before entering the packaging stage.

    Product options and specifications are not part of the per-SKU progress
    rows.  Previously they triggered invisible provider calls from inside
    ``build_catalog_language_pack`` after the UI already showed every SKU as
    processed.  Translate them here in bounded, resumable checkpoints so the
    PACKAGING and UPLOADING stages are provider-free and short-lived.

    Returns ``True`` when a requested pause was acknowledged.
    """

    values = catalog_language_pack_translatable_values(rows)
    seed = catalog_language_pack_translation_seed(
        rows,
        sku_translations=sku_translations,
        previous_payload=previous_payload,
        reuse_previous=reuse_previous,
    )
    _available, missing_by_locale = _batch_translation_availability(
        tenant_id=job.tenant_id,
        target_locale=job.target_locale,
        identity=translator.identity,
        values=values,
        seed=seed,
    )
    missing_count = sum(len(group) for group in missing_by_locale.values())
    previous_total, previous_processed = _job_finalization_counts(job)
    inferred_processed = max(0, previous_total - missing_count)
    processed = max(previous_processed, inferred_processed)
    total = max(previous_total, processed + missing_count)
    _save_job_finalization_counts(job, total=total, processed=processed)

    if missing_count == 0:
        _save_job_finalization_counts(job, total=total, processed=total)
        job.current_sku_id = None
        job.current_sku_name = None
        job.updated_at = utcnow()
        session.commit()
        return False

    provider_batch_items, provider_batch_characters = (
        resolved_catalog_translation_batch_limits(session)
    )
    provider_concurrency = resolved_catalog_translation_concurrency(session)
    checkpoint_items = provider_batch_items * provider_concurrency
    checkpoint_characters = provider_batch_characters * provider_concurrency
    checkpoints = [
        (source_locale, batch)
        for source_locale, group in missing_by_locale.items()
        for batch in _translation_value_checkpoint_batches(
            group,
            max_items=checkpoint_items,
            max_characters=checkpoint_characters,
        )
    ]

    for source_locale, batch in checkpoints:
        if _pause_at_safe_checkpoint(session, job):
            return True
        job.current_sku_id = None
        job.current_sku_name = (
            "正在补全规格、分类和选项翻译"
            f"（{processed} / {total} 项）"
        )
        job.updated_at = utcnow()
        session.commit()
        translated = translate_values_with_memory(
            tenant_id=job.tenant_id,
            translator=translator,
            values=batch,
            source_locale=source_locale,
            target_locale=job.target_locale,
            batch_size=provider_batch_items,
            batch_characters=provider_batch_characters,
            concurrency=provider_concurrency,
        )
        unresolved = [value for value in batch if value not in translated]
        if unresolved:
            raise TranslationProviderError(
                f"语言包仍有 {len(unresolved)} 个字段翻译失败，请从断点继续。",
                recover_with_smaller_batches=True,
            )
        processed += len(batch)
        _save_job_finalization_counts(job, total=total, processed=processed)
        job.current_sku_name = (
            "正在补全规格、分类和选项翻译"
            f"（{processed} / {total} 项）"
        )
        job.updated_at = utcnow()
        session.commit()
        if _pause_at_safe_checkpoint(session, job):
            return True

    _available, still_missing = _batch_translation_availability(
        tenant_id=job.tenant_id,
        target_locale=job.target_locale,
        identity=translator.identity,
        values=values,
        seed=seed,
    )
    unresolved_count = sum(len(group) for group in still_missing.values())
    if unresolved_count:
        raise TranslationProviderError(
            f"语言包仍有 {unresolved_count} 个字段未完成翻译，请从断点继续。"
        )
    _save_job_finalization_counts(job, total=total, processed=total)
    job.current_sku_id = None
    job.current_sku_name = None
    job.updated_at = utcnow()
    session.commit()
    return False


def _qwen_batch_error_summary(content: bytes | None) -> str | None:
    if not content:
        return None
    messages: list[str] = []
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    for line in lines[:20]:
        try:
            row = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        error = row.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
        else:
            message = None
        if isinstance(message, str) and message.strip():
            messages.append(" ".join(message.split())[:200])
        if len(messages) >= 3:
            break
    return "；".join(dict.fromkeys(messages)) or None


def _update_external_batch_status(
    job: CatalogTranslationJobRow,
    status: object,
) -> None:
    job.external_batch_id = getattr(status, "id")
    job.external_batch_status = getattr(status, "status")
    job.external_input_file_id = (
        getattr(status, "input_file_id") or job.external_input_file_id
    )
    job.external_output_file_id = getattr(status, "output_file_id")
    job.external_error_file_id = getattr(status, "error_file_id")
    job.external_total_requests = max(
        job.external_total_requests,
        int(getattr(status, "total_requests")),
    )
    job.external_completed_requests = int(
        getattr(status, "completed_requests")
    )
    job.external_failed_requests = int(getattr(status, "failed_requests"))
    job.updated_at = utcnow()


def _clear_qwen_batch_checkpoint(
    job: CatalogTranslationJobRow,
    *,
    clear_payload: bool,
) -> tuple[str, ...]:
    """Clear transport state atomically; remote files are deleted afterward."""

    file_ids = tuple(dict.fromkeys(
        value
        for value in (
            job.external_input_file_id,
            job.external_output_file_id,
            job.external_error_file_id,
        )
        if value
    ))
    if clear_payload:
        job.batch_request_payload = {}
    job.external_input_file_id = None
    job.external_batch_id = None
    job.external_output_file_id = None
    job.external_error_file_id = None
    job.external_batch_status = None
    job.external_total_requests = 0
    job.external_completed_requests = 0
    job.external_failed_requests = 0
    job.updated_at = utcnow()
    return file_ids


def _delete_qwen_batch_files(
    client: QwenBatchClient,
    file_ids: tuple[str, ...],
) -> None:
    for file_id in file_ids:
        try:
            client.delete_file(file_id)
        except TranslationProviderError:
            logger.warning("could not delete stale Qwen Batch file %s", file_id)


def _run_qwen_batch_translation_job(
    session: Session,
    *,
    job: CatalogTranslationJobRow,
    first_run: bool,
) -> None:
    configuration = resolved_qwen_batch_configuration(session)
    identity = configuration.identity
    client = QwenBatchClient(
        configuration,
        production=os.getenv("APP_ENV", "development").strip().lower()
        in {"production", "staging"},
    )
    storage = configured_language_package_storage()
    snapshot = (
        job.batch_request_payload
        if isinstance(job.batch_request_payload, dict)
        else {}
    )
    requests = snapshot.get("requests")
    requests = requests if isinstance(requests, list) else []

    if snapshot:
        checkpoint_rows = public_catalog_repository.list_all_public_catalog_rows(
            session,
            tenant_id=job.tenant_id,
            now=utcnow(),
        )
        catalog_changed = (
            snapshot.get("catalog_digest")
            != catalog_rows_source_digest(checkpoint_rows)
        )
        unusable_terminal_task = (
            job.external_batch_status in QWEN_BATCH_TERMINAL_STATUSES
            and (
                job.external_batch_status != "completed"
                or not job.external_output_file_id
            )
        )
        if catalog_changed or unusable_terminal_task:
            # Text imported before a catalog change remains reusable through
            # translation memory.  Only the obsolete transport checkpoint is
            # discarded, so the next file contains the current missing text.
            stale_file_ids = _clear_qwen_batch_checkpoint(
                job,
                clear_payload=True,
            )
            session.commit()
            _delete_qwen_batch_files(client, stale_file_ids)
            snapshot = {}
            requests = []

    if not snapshot:
        rows = public_catalog_repository.list_all_public_catalog_rows(
            session,
            tenant_id=job.tenant_id,
            now=utcnow(),
        )
        sources = [catalog_translation_source(row) for row in rows]
        sources_by_id = {source.sku_id: source for source in sources}
        forced_ids = _forced_sku_ids(job)
        stored_remaining = _remaining_sku_ids(job)
        forced_resume = not first_run and bool(forced_ids) and bool(stored_remaining)
        preserve_progress = (
            not first_run
            and not forced_ids
            and (bool(stored_remaining) or job.processed_skus >= job.total_skus)
        )
        if forced_ids and not forced_resume:
            candidates = [
                sources_by_id[sku_id]
                for sku_id in forced_ids
                if sku_id in sources_by_id
            ]
        elif forced_resume or (preserve_progress and job.mode == "FULL_REBUILD"):
            candidates = [
                sources_by_id[sku_id]
                for sku_id in stored_remaining
                if sku_id in sources_by_id
            ]
        else:
            candidates, _stale = _pending_sources(
                session,
                tenant_id=job.tenant_id,
                target_locale=job.target_locale,
                sources=sources,
                full_rebuild=job.mode == "FULL_REBUILD",
            )
        current_pack = translation_repository.language_pack(
            session,
            tenant_id=job.tenant_id,
            target_locale=job.target_locale,
        )
        previous_payload = load_language_pack_payload(storage, current_pack)
        sku_translations = translation_repository.translation_map(
            session,
            tenant_id=job.tenant_id,
            sku_ids=[source.sku_id for source in sources],
            target_locale=job.target_locale,
        )
        values = catalog_language_pack_translatable_values(rows)
        seed = (
            {}
            if job.mode == "FULL_REBUILD"
            else catalog_language_pack_translation_seed(
                rows,
                sku_translations=sku_translations,
                previous_payload=previous_payload,
                reuse_previous=bool(current_pack),
            )
        )
        forced_values = (
            set(
                catalog_language_pack_translatable_values(
                    [row for row in rows if row[1].id in set(forced_ids)]
                )
            )
            if forced_ids
            else set()
        )
        _available, missing_by_locale = _batch_translation_availability(
            tenant_id=job.tenant_id,
            target_locale=job.target_locale,
            identity=identity,
            values=values,
            seed=seed,
            force_refresh_values=(set(values) if job.mode == "FULL_REBUILD" else forced_values),
        )
        requests = qwen_batch_translation_requests(
            missing_by_locale,
            job_id=job.id,
        )
        snapshot = {
            "schema_version": 2,
            "catalog_digest": catalog_rows_source_digest(rows),
            "requests": requests,
            "candidate_source_hashes": {
                str(source.sku_id): source.source_hash for source in candidates
            },
            # A failed packaging/upload step may be resumed after every SKU
            # translation row was already committed.  Keep that completed
            # prefix separate from the candidates in this Batch snapshot so a
            # retry with zero pending SKUs cannot reset progress back to zero.
            "processed_skus_before_batch": (
                job.processed_skus if preserve_progress else 0
            ),
            "value_count": len(values),
        }
        job.batch_request_payload = snapshot
        translation_value_count = sum(
            _qwen_request_value_count(request) for request in requests
        )
        snapshot = _save_qwen_batch_progress(
            job,
            total=translation_value_count,
            processed=0,
            retry_generation=0,
        )
        job.provider = identity.provider
        job.provider_version = identity.version
        if not preserve_progress and not forced_resume:
            job.total_skus = len(candidates)
            job.processed_skus = 0
            job.failed_skus = 0
            job.failure_details = []
        else:
            job.total_skus = job.processed_skus + len(candidates)
        job.remaining_sku_ids = [str(source.sku_id) for source in candidates]
        job.external_total_requests = len(requests)
        job.stage = "TRANSLATING"
        job.updated_at = utcnow()
        session.commit()

    requests = [
        dict(request)
        for request in requests
        if isinstance(request, dict)
    ]
    requests, rows_by_request = _ensure_qwen_batch_rows(
        session,
        job=job,
        requests=requests,
    )
    snapshot = dict(job.batch_request_payload or snapshot)
    snapshot["requests"] = requests
    job.batch_request_payload = snapshot
    translation_total, translation_processed = _job_qwen_batch_counts(job)
    if translation_total == 0 and requests:
        translation_total = sum(
            _qwen_request_value_count(request) for request in requests
        )
        snapshot = _save_qwen_batch_progress(
            job,
            total=translation_total,
            processed=translation_processed,
        )
    job.external_total_requests = max(
        job.external_total_requests,
        len(requests),
    )
    session.commit()

    if _pause_at_safe_checkpoint(session, job):
        return

    while requests:
        snapshot = dict(job.batch_request_payload or snapshot)
        if (
            job.external_batch_id
            and job.external_batch_id in _qwen_imported_batch_ids(snapshot)
        ):
            # The model result was already imported before a later packaging
            # or object-storage failure. Do not create or charge another task.
            break

        _mark_qwen_batch_rows_running(rows_by_request)
        job.external_total_requests = max(
            job.external_total_requests,
            len(requests),
        )
        job.stage = "TRANSLATING"
        job.updated_at = utcnow()
        session.commit()

        if not job.external_input_file_id:
            content = client.jsonl_content(
                requests,
                target_locale=job.target_locale,
            )
            job.external_input_file_id = client.upload_jsonl(
                content,
                filename=f"catalog-{job.id}.jsonl",
            )
            job.external_batch_status = "file_uploaded"
            job.updated_at = utcnow()
            session.commit()

        if not job.external_batch_id:
            status = client.find_batch(job.external_input_file_id)
            if status is None:
                status = client.create_batch(
                    job.external_input_file_id,
                    name=f"ATC-{job.target_locale}-{str(job.id)[:8]}",
                    description=(
                        f"Catalog {job.mode.lower()} translation for tenant "
                        f"{str(job.tenant_id)[:8]}"
                    ),
                )
            _update_external_batch_status(job, status)
            session.commit()

        poll_seconds = _positive_environment(
            "QWEN_BATCH_POLL_SECONDS",
            10,
            maximum=60,
        )
        while job.external_batch_status not in QWEN_BATCH_TERMINAL_STATUSES:
            if _pause_at_safe_checkpoint(session, job):
                return
            time.sleep(poll_seconds)
            status = client.retrieve_batch(job.external_batch_id)
            _update_external_batch_status(job, status)
            session.commit()

        if job.external_batch_status != "completed":
            error_content = (
                client.download_file(job.external_error_file_id)
                if job.external_error_file_id
                else None
            )
            detail = _qwen_batch_error_summary(error_content)
            suffix = f"：{detail}" if detail else ""
            message = f"Qwen Batch task {job.external_batch_status}{suffix}"
            _record_qwen_batch_transport_failure(
                session,
                requests=requests,
                rows_by_request=rows_by_request,
                error_message=message,
            )
            session.commit()
            raise TranslationProviderError(message)
        if not job.external_output_file_id:
            message = "Qwen Batch completed without an output file"
            _record_qwen_batch_transport_failure(
                session,
                requests=requests,
                rows_by_request=rows_by_request,
                error_message=message,
            )
            session.commit()
            raise TranslationProviderError(message)
        try:
            parse_result = client.parse_output(
                client.download_file(job.external_output_file_id),
                requests,
                target_locale=job.target_locale,
            )
        except TranslationProviderError as exc:
            _record_qwen_batch_transport_failure(
                session,
                requests=requests,
                rows_by_request=rows_by_request,
                error_message=str(exc),
            )
            stale_file_ids = _clear_qwen_batch_checkpoint(
                job,
                clear_payload=False,
            )
            job.external_total_requests = len(requests)
            session.commit()
            _delete_qwen_batch_files(client, stale_file_ids)
            raise
        for source_locale, translations in (
            parse_result.translations_by_locale.items()
        ):
            store_translation_values(
                tenant_id=job.tenant_id,
                translations=translations,
                source_locale=source_locale,
                target_locale=job.target_locale,
                provider=identity.provider,
                provider_version=identity.version,
            )

        _record_qwen_batch_parse_result(
            session,
            requests=requests,
            rows_by_request=rows_by_request,
            result=parse_result,
        )
        translation_total, translation_processed = _job_qwen_batch_counts(job)
        successful_ids = set(parse_result.successful_request_ids)
        newly_processed = sum(
            _qwen_request_value_count(request)
            for request in requests
            if str(request.get("custom_id", "")) in successful_ids
        )
        progress_rows = public_catalog_repository.list_all_public_catalog_rows(
            session,
            tenant_id=job.tenant_id,
            now=utcnow(),
        )
        completed_candidate_skus = _qwen_complete_candidate_sku_count(
            session,
            job=job,
            identity=identity,
            rows=progress_rows,
            snapshot=snapshot,
            storage=storage,
        )
        current_batch_id = job.external_batch_id
        retry_generation = _qwen_retry_generation(snapshot)
        snapshot = _save_qwen_batch_progress(
            job,
            total=translation_total,
            processed=translation_processed + newly_processed,
            imported_batch_id=current_batch_id,
            retry_generation=retry_generation,
            processed_skus=completed_candidate_skus,
        )
        translation_total, translation_processed = _job_qwen_batch_counts(job)
        job.current_sku_name = (
            f"已导入翻译字段（{translation_processed} / "
            f"{translation_total} 项）"
        )
        job.updated_at = utcnow()

        if parse_result.failures:
            next_generation = retry_generation + 1
            if next_generation > _QWEN_BATCH_MAX_RETRY_GENERATION:
                stale_file_ids = _clear_qwen_batch_checkpoint(
                    job,
                    clear_payload=False,
                )
                job.external_total_requests = len(requests)
                session.commit()
                _delete_qwen_batch_files(client, stale_file_ids)
                raise TranslationProviderError(
                    f"已保存 {translation_processed} / {translation_total} 个翻译字段；"
                    f"仍有 {parse_result.failed_values} 个字段需要按失败批次重试"
                )
            retry_requests, split_parent_ids = _qwen_retry_requests(
                parse_result.failures,
                job_id=job.id,
                generation=next_generation,
            )
            if not retry_requests:
                session.commit()
                raise TranslationProviderError(
                    "Qwen Batch failed subsets could not be reconstructed"
                )
            _mark_qwen_split_parents(
                session,
                tenant_id=job.tenant_id,
                parent_ids=split_parent_ids,
            )
            retry_requests, next_rows_by_request = _ensure_qwen_batch_rows(
                session,
                job=job,
                requests=retry_requests,
            )
            snapshot = dict(job.batch_request_payload or snapshot)
            snapshot["requests"] = retry_requests
            job.batch_request_payload = snapshot
            snapshot = _save_qwen_batch_progress(
                job,
                total=translation_total,
                processed=translation_processed,
                imported_batch_id=current_batch_id,
                retry_generation=next_generation,
            )
            stale_file_ids = _clear_qwen_batch_checkpoint(
                job,
                clear_payload=False,
            )
            job.external_total_requests = len(retry_requests)
            job.stage = "TRANSLATING"
            job.updated_at = utcnow()
            session.commit()
            _delete_qwen_batch_files(client, stale_file_ids)
            requests = retry_requests
            rows_by_request = next_rows_by_request
            if _pause_at_safe_checkpoint(session, job):
                return
            continue

        session.commit()
        break

    # The cloud task can take hours. Never publish a mixed snapshot if catalog
    # content changed while it was running; successful text stays in memory and
    # the next incremental run submits only the new remainder.
    rows = public_catalog_repository.list_all_public_catalog_rows(
        session,
        tenant_id=job.tenant_id,
        now=utcnow(),
    )
    if snapshot.get("catalog_digest") != catalog_rows_source_digest(rows):
        sources = [catalog_translation_source(row) for row in rows]
        pending, _stale = _pending_sources(
            session,
            tenant_id=job.tenant_id,
            target_locale=job.target_locale,
            sources=sources,
            full_rebuild=False,
        )
        job.remaining_sku_ids = [str(source.sku_id) for source in pending]
        session.commit()
        raise TranslationProviderError(
            "商品在 Batch 执行期间发生了变更，请继续任务翻译新增内容"
        )

    sources = [catalog_translation_source(row) for row in rows]
    source_by_id = {str(source.sku_id): source for source in sources}
    current_pack = translation_repository.language_pack(
        session,
        tenant_id=job.tenant_id,
        target_locale=job.target_locale,
    )
    previous_payload = load_language_pack_payload(storage, current_pack)
    sku_translations = translation_repository.translation_map(
        session,
        tenant_id=job.tenant_id,
        sku_ids=[source.sku_id for source in sources],
        target_locale=job.target_locale,
    )
    values = catalog_language_pack_translatable_values(rows)
    seed = (
        {}
        if job.mode == "FULL_REBUILD"
        else catalog_language_pack_translation_seed(
            rows,
            sku_translations=sku_translations,
            previous_payload=previous_payload,
            reuse_previous=bool(current_pack),
        )
    )
    translations, missing_by_locale = _batch_translation_availability(
        tenant_id=job.tenant_id,
        target_locale=job.target_locale,
        identity=identity,
        values=values,
        seed=seed,
    )
    if missing_by_locale:
        raise TranslationProviderError(
            "Batch translation memory is incomplete after result import"
        )

    candidate_hashes = snapshot.get("candidate_source_hashes")
    candidate_hashes = (
        candidate_hashes if isinstance(candidate_hashes, dict) else {}
    )
    processed_before_batch = snapshot.get("processed_skus_before_batch", 0)
    processed_before_batch = (
        max(0, int(processed_before_batch))
        if isinstance(processed_before_batch, (int, float))
        else 0
    )
    translated_ids: list[str] = []
    for sku_id, source_hash in candidate_hashes.items():
        source = source_by_id.get(str(sku_id))
        if source is None or source.source_hash != source_hash:
            continue
        result = catalog_translation_result_from_values(
            source,
            translations,
            source_locale=job.source_locale,
            target_locale=job.target_locale,
        )
        translation_repository.save_translation(
            session,
            tenant_id=job.tenant_id,
            source_locale=job.source_locale,
            target_locale=job.target_locale,
            source=source,
            result=result,
            provider=identity.provider,
            provider_version=identity.version,
        )
        translated_ids.append(str(source.sku_id))
    job.processed_skus = min(
        job.total_skus,
        processed_before_batch + len(translated_ids),
    )
    job.failed_skus = max(0, len(candidate_hashes) - len(translated_ids))
    job.remaining_sku_ids = [
        sku_id for sku_id in candidate_hashes if sku_id not in set(translated_ids)
    ]
    if job.failed_skus:
        session.commit()
        raise TranslationProviderError(
            f"{job.failed_skus} 个 SKU 在 Batch 结果应用时发生变化"
        )
    session.commit()

    job.stage = "PACKAGING"
    job.current_sku_id = None
    job.current_sku_name = None
    job.updated_at = utcnow()
    session.commit()
    if _pause_at_safe_checkpoint(session, job):
        return

    sku_translations = translation_repository.translation_map(
        session,
        tenant_id=job.tenant_id,
        sku_ids=[source.sku_id for source in sources],
        target_locale=job.target_locale,
    )
    next_version = (current_pack.version if current_pack else 0) + 1
    build = build_catalog_language_pack(
        tenant_id=job.tenant_id,
        rows=rows,
        source_locale=job.source_locale,
        target_locale=job.target_locale,
        version=next_version,
        translator=_CachedOnlyTranslationProvider(identity),
        sku_translations=sku_translations,
        previous_payload=previous_payload,
        reuse_previous=bool(current_pack),
        full_rebuild=job.mode == "FULL_REBUILD",
        force_rebuild_sku_ids=set(_forced_sku_ids(job)),
    )
    object_key = language_pack_object_key(
        tenant_id=job.tenant_id,
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
        tenant_id=job.tenant_id,
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
        provider=identity.provider,
        provider_version=identity.version,
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

    # DashScope keeps uploaded Batch files indefinitely. They are temporary
    # transport artifacts here, so clean them after the immutable package and
    # database checkpoint have both committed.
    for file_id in dict.fromkeys(
        value
        for value in (
            job.external_input_file_id,
            job.external_output_file_id,
            job.external_error_file_id,
        )
        if value
    ):
        try:
            client.delete_file(file_id)
        except TranslationProviderError:
            logger.warning("could not delete completed Qwen Batch file %s", file_id)


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

            if job.execution_mode == "QWEN_BATCH":
                _run_qwen_batch_translation_job(
                    session,
                    job=job,
                    first_run=first_run,
                )
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
            sku_translations = translation_repository.translation_map(
                session,
                tenant_id=tenant_id,
                sku_ids=[source.sku_id for source in sources],
                target_locale=job.target_locale,
            )
            if _prepare_realtime_language_pack_values(
                session,
                job=job,
                translator=translator,
                rows=rows,
                sku_translations=sku_translations,
                previous_payload=previous_payload,
                reuse_previous=(
                    bool(current_pack) and job.mode != "FULL_REBUILD"
                ),
            ):
                return
            job.stage = "PACKAGING"
            job.current_sku_id = None
            job.current_sku_name = None
            job.updated_at = utcnow()
            session.commit()

            if _pause_at_safe_checkpoint(session, job):
                return

            next_version = (current_pack.version if current_pack else 0) + 1
            build = build_catalog_language_pack(
                tenant_id=tenant_id,
                rows=rows,
                source_locale=job.source_locale,
                target_locale=job.target_locale,
                version=next_version,
                # The provider work is complete before PACKAGING. If a field
                # escaped the resumable preparation above, fail safely instead
                # of hiding another long model call behind 97% progress.
                translator=_CachedOnlyTranslationProvider(translator.identity),
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
    executor = _translation_executor
    try:
        with SessionLocal() as session:
            set_request_context(
                session,
                organization_id=organization_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            execution_mode = session.scalar(
                select(CatalogTranslationJobRow.execution_mode).where(
                    CatalogTranslationJobRow.tenant_id == tenant_id,
                    CatalogTranslationJobRow.id == job_id,
                )
            )
            session.rollback()
        if execution_mode == "QWEN_BATCH":
            executor = _qwen_batch_executor
    except Exception:
        # Falling back to the conservative executor delays a submission but
        # never loses it; the worker itself still reads the persisted mode.
        logger.exception(
            "could not select translation executor for job %s",
            job_id,
        )
    executor.submit(
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
    # Qwen Batch transport checkpoints deliberately survive a local failure.
    # The worker can replay a completed output after an upload/package outage,
    # resume polling an in-flight task, or replace a stale/failed cloud task
    # without creating a duplicate paid submission.
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


def _latest_resumable_job_for_mode(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
    execution_mode: str,
) -> CatalogTranslationJobRow | None:
    return session.scalar(
        select(CatalogTranslationJobRow)
        .where(
            CatalogTranslationJobRow.tenant_id == tenant_id,
            CatalogTranslationJobRow.target_locale == target_locale,
            CatalogTranslationJobRow.execution_mode == execution_mode,
            CatalogTranslationJobRow.status.in_(("PAUSED", "FAILED")),
        )
        .order_by(CatalogTranslationJobRow.created_at.desc())
        .limit(1)
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
    execution_mode = _requested_job_execution_mode(session, request)
    try:
        if execution_mode == "QWEN_BATCH":
            identity = resolved_qwen_batch_configuration(session).identity
        else:
            identity = resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            ).identity
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
        if not _supersede_paused_job_for_mode(
            session,
            job=existing,
            execution_mode=execution_mode,
            explicitly_requested=request.execution_mode is not None,
        ):
            return _job_response(existing)

    # A task from the other engine may be newer than a saved checkpoint.  An
    # explicitly selected action must resume the matching engine's checkpoint
    # instead of silently submitting duplicate Batch work.
    if request.execution_mode is not None:
        resumable = _latest_resumable_job_for_mode(
            session,
            tenant_id=context.tenant_id,
            target_locale=request.target_locale,
            execution_mode=execution_mode,
        )
        if resumable is not None:
            return resume_translation_job(
                session,
                context=context,
                job_id=resumable.id,
            )

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
        execution_mode=execution_mode,
        status="QUEUED" if work_required else "SUCCEEDED",
        stage="QUEUED" if work_required else "PUBLISHED",
        total_skus=len(candidates),
        processed_skus=0,
        failed_skus=0,
        provider=identity.provider,
        provider_version=identity.version,
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
