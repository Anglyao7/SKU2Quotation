"""On-demand, tenant-scoped translation memory for public catalog text."""

from __future__ import annotations

import hashlib
import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..catalog_translation_models import CatalogTextTranslationRow
from ..database import SessionLocal, set_public_tenant_context
from ..model_mixins import utcnow
from .catalog_translation import translate_catalog_values
from .translation import TranslationProvider, TranslationProviderError


logger = logging.getLogger(__name__)
_TRANSLATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="catalog-translation",
)
_SINGLEFLIGHT_LOCK = Lock()
_INFLIGHT_TRANSLATIONS: dict[tuple[str, ...], Future[str]] = {}
_REDIS_LOCK = Lock()
_CLEANUP_LOCK = Lock()
_redis_client: Any | None = None
_redis_client_url: str | None = None
_redis_disabled_until = 0.0
_last_cleanup_by_tenant: dict[UUID, float] = {}


def _positive_int_environment(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(value, maximum))


_PROVIDER_CONCURRENCY = _positive_int_environment(
    "PUBLIC_LIVE_TRANSLATION_CONCURRENCY",
    3,
    maximum=8,
)
_PROVIDER_SEMAPHORE = BoundedSemaphore(_PROVIDER_CONCURRENCY)


def translation_source_hash(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _memory_key(
    *,
    tenant_id: UUID,
    source_locale: str,
    target_locale: str,
    provider: str,
    provider_version: str,
    source_hash: str,
) -> tuple[str, ...]:
    return (
        str(tenant_id),
        source_locale,
        target_locale,
        provider,
        provider_version,
        source_hash,
    )


def _redis_key(memory_key: tuple[str, ...]) -> str:
    digest = hashlib.sha256("\0".join(memory_key).encode("utf-8")).hexdigest()
    return f"atc:catalog-translation:v1:{digest}"


def _configured_redis_client() -> Any | None:
    global _redis_client, _redis_client_url, _redis_disabled_until
    url = os.getenv("REDIS_URL", "").strip()
    if not url or monotonic() < _redis_disabled_until:
        return None
    with _REDIS_LOCK:
        if _redis_client is not None and _redis_client_url == url:
            return _redis_client
        try:
            from redis import Redis

            _redis_client = Redis.from_url(
                url,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                health_check_interval=30,
                decode_responses=True,
            )
            _redis_client_url = url
            return _redis_client
        except Exception:
            _redis_client = None
            _redis_client_url = None
            _redis_disabled_until = monotonic() + 30
            return None


def _redis_get_many(
    memory_keys_by_source: dict[str, tuple[str, ...]],
) -> dict[str, str]:
    global _redis_client, _redis_disabled_until
    client = _configured_redis_client()
    if client is None or not memory_keys_by_source:
        return {}
    sources = list(memory_keys_by_source)
    try:
        values = client.mget(
            [_redis_key(memory_keys_by_source[source]) for source in sources]
        )
    except Exception:
        with _REDIS_LOCK:
            _redis_client = None
            _redis_disabled_until = monotonic() + 30
        return {}
    return {
        source: translated
        for source, translated in zip(sources, values, strict=True)
        if isinstance(translated, str) and translated.strip()
    }


def _redis_store_many(
    memory_keys_by_source: dict[str, tuple[str, ...]],
    translations: dict[str, str],
) -> None:
    global _redis_client, _redis_disabled_until
    client = _configured_redis_client()
    if client is None or not translations:
        return
    ttl_seconds = _positive_int_environment(
        "PUBLIC_TRANSLATION_REDIS_TTL_SECONDS",
        21_600,
        maximum=604_800,
    )
    try:
        pipeline = client.pipeline(transaction=False)
        for source, translated in translations.items():
            pipeline.set(
                _redis_key(memory_keys_by_source[source]),
                translated,
                ex=ttl_seconds,
            )
        pipeline.execute()
    except Exception:
        with _REDIS_LOCK:
            _redis_client = None
            _redis_disabled_until = monotonic() + 30


def _database_get_many(
    *,
    tenant_id: UUID,
    source_locale: str,
    target_locale: str,
    provider: str,
    provider_version: str,
    sources_by_hash: dict[str, str],
) -> dict[str, str]:
    if not sources_by_hash:
        return {}
    try:
        with SessionLocal() as session:
            set_public_tenant_context(session, tenant_id=tenant_id)
            rows = list(
                session.scalars(
                    select(CatalogTextTranslationRow).where(
                        CatalogTextTranslationRow.tenant_id == tenant_id,
                        CatalogTextTranslationRow.source_locale == source_locale,
                        CatalogTextTranslationRow.target_locale == target_locale,
                        CatalogTextTranslationRow.provider == provider,
                        CatalogTextTranslationRow.provider_version
                        == provider_version,
                        CatalogTextTranslationRow.source_hash.in_(sources_by_hash),
                    )
                ).all()
            )
            now = utcnow()
            stale_touch_before = now - timedelta(hours=24)
            stale_ids = [
                row.id
                for row in rows
                if _as_utc(row.last_accessed_at) < stale_touch_before
            ]
            if stale_ids:
                session.execute(
                    update(CatalogTextTranslationRow)
                    .where(
                        CatalogTextTranslationRow.tenant_id == tenant_id,
                        CatalogTextTranslationRow.id.in_(stale_ids),
                    )
                    .values(last_accessed_at=now, updated_at=now)
                )
                session.commit()
            return {
                row.source_text: row.translated_text
                for row in rows
                if sources_by_hash.get(row.source_hash) == row.source_text
                and row.translated_text.strip()
            }
    except SQLAlchemyError:
        logger.warning(
            "catalog translation memory lookup failed; continuing without cache"
        )
        return {}


def _database_store_many(
    *,
    tenant_id: UUID,
    source_locale: str,
    target_locale: str,
    provider: str,
    provider_version: str,
    translations: dict[str, str],
) -> None:
    if not translations:
        return
    now = utcnow()
    records = [
        {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "source_locale": source_locale,
            "target_locale": target_locale,
            "source_hash": translation_source_hash(source),
            "source_text": source,
            "translated_text": translated,
            "provider": provider,
            "provider_version": provider_version,
            "last_accessed_at": now,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        for source, translated in translations.items()
    ]
    conflict_columns = [
        "tenant_id",
        "source_locale",
        "target_locale",
        "provider",
        "provider_version",
        "source_hash",
    ]
    try:
        with SessionLocal() as session:
            set_public_tenant_context(session, tenant_id=tenant_id)
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                statement = postgresql_insert(CatalogTextTranslationRow).values(
                    records
                )
                statement = statement.on_conflict_do_update(
                    index_elements=conflict_columns,
                    set_={
                        "source_text": statement.excluded.source_text,
                        "translated_text": statement.excluded.translated_text,
                        "last_accessed_at": statement.excluded.last_accessed_at,
                        "updated_at": statement.excluded.updated_at,
                        "deleted_at": None,
                    },
                )
                session.execute(statement)
            elif dialect == "sqlite":
                statement = sqlite_insert(CatalogTextTranslationRow).values(records)
                statement = statement.on_conflict_do_update(
                    index_elements=conflict_columns,
                    set_={
                        "source_text": statement.excluded.source_text,
                        "translated_text": statement.excluded.translated_text,
                        "last_accessed_at": statement.excluded.last_accessed_at,
                        "updated_at": statement.excluded.updated_at,
                        "deleted_at": None,
                    },
                )
                session.execute(statement)
            else:  # pragma: no cover - supported deployments use PostgreSQL/SQLite
                session.add_all(
                    CatalogTextTranslationRow(**record) for record in records
                )
            session.commit()
            try:
                _cleanup_stale_rows(session, tenant_id=tenant_id, now=now)
            except SQLAlchemyError:
                session.rollback()
                logger.warning("catalog translation memory cleanup failed")
    except SQLAlchemyError:
        logger.warning(
            "catalog translation memory persistence failed; response remains usable"
        )


def _cleanup_stale_rows(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
) -> None:
    interval_seconds = _positive_int_environment(
        "PUBLIC_TRANSLATION_CLEANUP_INTERVAL_SECONDS",
        3_600,
        maximum=86_400,
    )
    current_tick = monotonic()
    with _CLEANUP_LOCK:
        last_cleanup = _last_cleanup_by_tenant.get(tenant_id, 0.0)
        if current_tick - last_cleanup < interval_seconds:
            return
        _last_cleanup_by_tenant[tenant_id] = current_tick

    retention_days = _positive_int_environment(
        "PUBLIC_TRANSLATION_RETENTION_DAYS",
        60,
        maximum=3_650,
    )
    batch_size = _positive_int_environment(
        "PUBLIC_TRANSLATION_CLEANUP_BATCH_SIZE",
        500,
        maximum=5_000,
    )
    stale_ids = (
        select(CatalogTextTranslationRow.id)
        .where(
            CatalogTextTranslationRow.tenant_id == tenant_id,
            CatalogTextTranslationRow.last_accessed_at
            < now - timedelta(days=retention_days),
        )
        .order_by(CatalogTextTranslationRow.last_accessed_at)
        .limit(batch_size)
    )
    session.execute(
        delete(CatalogTextTranslationRow).where(
            CatalogTextTranslationRow.tenant_id == tenant_id,
            CatalogTextTranslationRow.id.in_(stale_ids),
        )
    )
    session.commit()


def _translation_batches(
    values: list[str],
    *,
    max_items: int,
    max_characters: int,
) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    current_size = 0
    for value in values:
        if current and (
            len(current) >= max_items
            or current_size + len(value) > max_characters
        ):
            batches.append(current)
            current = []
            current_size = 0
        current.append(value)
        current_size += len(value)
    if current:
        batches.append(current)
    return batches


def _translate_batch(
    translator: TranslationProvider,
    batch: list[str],
    *,
    source_locale: str,
    target_locale: str,
) -> list[str]:
    with _PROVIDER_SEMAPHORE:
        return translate_catalog_values(
            translator,
            batch,
            source_locale=source_locale,
            target_locale=target_locale,
        )


def _translate_uncached_values(
    translator: TranslationProvider,
    values: list[str],
    *,
    source_locale: str,
    target_locale: str,
) -> tuple[dict[str, str], dict[str, TranslationProviderError]]:
    batches = _translation_batches(
        values,
        max_items=_positive_int_environment(
            "PUBLIC_LIVE_TRANSLATION_BATCH_SIZE",
            24,
            maximum=100,
        ),
        max_characters=_positive_int_environment(
            "PUBLIC_LIVE_TRANSLATION_BATCH_CHARACTERS",
            1_800,
            maximum=100_000,
        ),
    )
    successes: dict[str, str] = {}
    failures: dict[str, TranslationProviderError] = {}
    futures = {
        _TRANSLATION_EXECUTOR.submit(
            _translate_batch,
            translator,
            batch,
            source_locale=source_locale,
            target_locale=target_locale,
        ): batch
        for batch in batches
    }
    for future in as_completed(futures):
        batch = futures[future]
        try:
            translated_values = future.result()
            successes.update(
                zip(batch, translated_values, strict=True)
            )
        except TranslationProviderError as exc:
            logger.warning("catalog translation batch failed: %s", exc)
            failures.update((value, exc) for value in batch)
        except Exception:
            logger.exception("unexpected catalog translation batch failure")
            safe_error = TranslationProviderError(
                "translation provider request failed"
            )
            failures.update((value, safe_error) for value in batch)
    return successes, failures


def translate_values_with_memory(
    *,
    tenant_id: UUID,
    translator: TranslationProvider,
    values: list[str],
    source_locale: str,
    target_locale: str,
) -> dict[str, str]:
    """Return available translations and cache only text users actually requested.

    Individual failed provider batches are omitted, allowing callers to fall
    back only those fields while successful batches remain translated.
    """

    normalized_by_original = {
        value: value.strip()
        for value in values
        if value and value.strip()
    }
    unique_sources = list(dict.fromkeys(normalized_by_original.values()))
    if not unique_sources or source_locale == target_locale:
        return {}

    identity = translator.identity
    memory_keys_by_source = {
        source: _memory_key(
            tenant_id=tenant_id,
            source_locale=source_locale,
            target_locale=target_locale,
            provider=identity.provider,
            provider_version=identity.version,
            source_hash=translation_source_hash(source),
        )
        for source in unique_sources
    }
    translations = _redis_get_many(memory_keys_by_source)
    database_sources = [
        source for source in unique_sources if source not in translations
    ]
    if database_sources:
        database_hits = _database_get_many(
            tenant_id=tenant_id,
            source_locale=source_locale,
            target_locale=target_locale,
            provider=identity.provider,
            provider_version=identity.version,
            sources_by_hash={
                translation_source_hash(source): source
                for source in database_sources
            },
        )
        translations.update(database_hits)
        _redis_store_many(memory_keys_by_source, database_hits)

    missing_sources = [
        source for source in unique_sources if source not in translations
    ]
    futures_by_source: dict[str, Future[str]] = {}
    leader_sources: list[str] = []
    with _SINGLEFLIGHT_LOCK:
        for source in missing_sources:
            key = memory_keys_by_source[source]
            future = _INFLIGHT_TRANSLATIONS.get(key)
            if future is None:
                future = Future()
                _INFLIGHT_TRANSLATIONS[key] = future
                leader_sources.append(source)
            futures_by_source[source] = future

    if leader_sources:
        successes: dict[str, str] = {}
        failures: dict[str, TranslationProviderError] = {}
        try:
            successes, failures = _translate_uncached_values(
                translator,
                leader_sources,
                source_locale=source_locale,
                target_locale=target_locale,
            )
            _database_store_many(
                tenant_id=tenant_id,
                source_locale=source_locale,
                target_locale=target_locale,
                provider=identity.provider,
                provider_version=identity.version,
                translations=successes,
            )
            _redis_store_many(memory_keys_by_source, successes)
        except Exception:
            logger.exception("unexpected translation-memory leader failure")
            safe_error = TranslationProviderError(
                "translation provider request failed"
            )
            failures.update(
                (source, safe_error)
                for source in leader_sources
                if source not in successes
            )
        with _SINGLEFLIGHT_LOCK:
            for source in leader_sources:
                future = futures_by_source[source]
                if source in successes:
                    future.set_result(successes[source])
                else:
                    future.set_exception(
                        failures.get(
                            source,
                            TranslationProviderError(
                                "translation provider request failed"
                            ),
                        )
                    )
                key = memory_keys_by_source[source]
                if _INFLIGHT_TRANSLATIONS.get(key) is future:
                    del _INFLIGHT_TRANSLATIONS[key]

    for source, future in futures_by_source.items():
        try:
            translations[source] = future.result()
        except TranslationProviderError:
            continue

    return {
        original: translations[normalized]
        for original, normalized in normalized_by_original.items()
        if normalized in translations
    }


def _reset_translation_memory_for_tests() -> None:
    global _redis_client, _redis_client_url, _redis_disabled_until
    with _REDIS_LOCK:
        _redis_client = None
        _redis_client_url = None
        _redis_disabled_until = 0.0
    with _SINGLEFLIGHT_LOCK:
        _INFLIGHT_TRANSLATIONS.clear()
    with _CLEANUP_LOCK:
        _last_cleanup_by_tenant.clear()
