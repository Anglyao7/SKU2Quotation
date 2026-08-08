from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog_translation_models import (
    CatalogLanguagePackRow,
    CatalogTranslationJobRow,
)
from ..catalog_translation_schemas import (
    CatalogTranslationFailure,
    CatalogTranslationJobResponse,
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
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)
from ..services.translation_configuration import (
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
        source_digest=pack.source_digest,
        content_encoding=pack.content_encoding,
        byte_size=pack.byte_size,
        product_count=pack.product_count,
        sku_count=pack.sku_count,
        category_count=pack.category_count,
        provider=pack.provider,
        provider_version=pack.provider_version,
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
        progress_percent=progress,
        current_sku_id=job.current_sku_id,
        current_sku_name=job.current_sku_name,
        provider=job.provider,
        provider_version=job.provider_version,
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
            CatalogTranslationJobRow.status.in_(("QUEUED", "RUNNING", "PAUSED")),
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
    job.status = "FAILED"
    job.stage = "FAILED"
    job.failed_skus = max(0, job.total_skus - job.processed_skus)
    job.error_message = "翻译任务因服务中断而停止，请重新发起。"
    job.current_sku_id = None
    job.current_sku_name = None
    job.completed_at = utcnow()
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
    provider = "deeplx" if configured else "not-configured"
    provider_version = "v1"
    if configured:
        try:
            translator = resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            )
            provider = translator.identity.provider
            provider_version = translator.identity.version
        except TranslationProviderError:
            configured = False

    rows = _all_rows(session, tenant_id=tenant_id)
    sources = [catalog_translation_source(row) for row in rows]
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
        or pack.provider != provider
        or pack.provider_version != provider_version
        or pack.storage_fingerprint != storage_status.fingerprint
    )
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
        package_outdated=package_outdated,
        package_storage_backend=storage_status.backend,
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


def _remaining_sku_ids(job: CatalogTranslationJobRow) -> list[UUID]:
    values: list[UUID] = []
    for raw in job.remaining_sku_ids or []:
        try:
            values.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return values


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
            )
        )
        if job is None or job.status != "QUEUED":
            return
        try:
            first_run = job.started_at is None
            previous_provider = (job.provider, job.provider_version)
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
            provider_changed = previous_provider != (
                translator.identity.provider,
                translator.identity.version,
            )
            sources_by_id = {source.sku_id: source for source in sources}
            stored_remaining = _remaining_sku_ids(job)
            preserve_progress = not first_run and not provider_changed
            if preserve_progress or (stored_remaining and not provider_changed):
                candidates = [
                    sources_by_id[sku_id]
                    for sku_id in stored_remaining
                    if sku_id in sources_by_id
                ]
            else:
                candidates, _stale = _pending_sources(
                    session,
                    tenant_id=tenant_id,
                    target_locale=job.target_locale,
                    sources=sources,
                    provider=translator.identity.provider,
                    provider_version=translator.identity.version,
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
            if preserve_progress:
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
            processed = job.processed_skus
            failures: list[dict[str, str]] = list(job.failure_details or [])
            remaining_ids = [str(source.sku_id) for source in candidates]
            for batch in batches:
                if _pause_at_safe_checkpoint(session, job):
                    return
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
                processed += len(translated_ids)
                translated_values = {str(sku_id) for sku_id in translated_ids}
                remaining_ids = [
                    sku_id
                    for sku_id in remaining_ids
                    if sku_id not in translated_values
                ]
                job.processed_skus = processed
                job.failed_skus += failed_in_batch
                job.failure_details = failures
                job.remaining_sku_ids = remaining_ids
                job.updated_at = utcnow()
                session.commit()

                if _pause_at_safe_checkpoint(session, job):
                    return

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
                full_rebuild=job.mode == "FULL_REBUILD",
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
            failed_job.remaining_sku_ids = []
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


def _managed_job(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
) -> CatalogTranslationJobRow:
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
    )
    if job.status == "RUNNING" and job.pause_requested_at is not None:
        job.pause_requested_at = None
        session.commit()
        return _job_response(job)
    if job.status != "PAUSED":
        raise ApplicationError(
            "CATALOG_TRANSLATION_JOB_NOT_RESUMABLE",
            "只有已暂停的翻译任务可以继续。",
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
    session.commit()
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
            "语言包存储尚未配置，请先配置 Cloudflare R2。",
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
        provider=translator.identity.provider,
        provider_version=translator.identity.version,
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
        and current_pack.provider == translator.identity.provider
        and current_pack.provider_version == translator.identity.version
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
