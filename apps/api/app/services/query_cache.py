"""Small, tenant-scoped Redis cache for expensive read models.

PostgreSQL remains the source of truth.  Cache failures are deliberately
fail-open: a Redis outage may make reads slower, but must never make catalog or
inventory APIs unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)

DOMAIN_CATALOG = "catalog"
DOMAIN_DASHBOARD = "dashboard"
DOMAIN_INVENTORY = "inventory"
DOMAIN_METADATA = "metadata"

_PENDING_INVALIDATIONS = "query_cache_pending_invalidations"
_CLIENT_LOCK = RLock()
_redis_client: Any | None = None
_redis_client_url: str | None = None
_redis_disabled_until = 0.0


@dataclass(frozen=True)
class CacheSlot:
    """A generation-pinned cache lookup.

    The key is resolved before the database query.  Storing through this same
    slot prevents a concurrent write from publishing stale data into a newer
    cache generation.
    """

    key: str | None
    value: Any | None = None
    hit: bool = False


def _enabled() -> bool:
    configured = os.getenv("QUERY_CACHE_ENABLED", "true").strip().lower()
    return configured in {"1", "true", "yes", "on"} and bool(
        os.getenv("REDIS_URL", "").strip()
    )


def configured_ttl(name: str, default: int, *, maximum: int = 3_600) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(value, maximum))


def _disable_temporarily(exc: Exception) -> None:
    global _redis_client, _redis_client_url, _redis_disabled_until
    with _CLIENT_LOCK:
        _redis_client = None
        _redis_client_url = None
        _redis_disabled_until = monotonic() + 30
    logger.warning("Query cache temporarily disabled: %s", type(exc).__name__)


def _client() -> Any | None:
    global _redis_client, _redis_client_url, _redis_disabled_until
    if not _enabled() or monotonic() < _redis_disabled_until:
        return None
    url = os.getenv("REDIS_URL", "").strip()
    with _CLIENT_LOCK:
        if _redis_client is not None and _redis_client_url == url:
            return _redis_client
        try:
            from redis import Redis

            _redis_client = Redis.from_url(
                url,
                socket_connect_timeout=0.15,
                socket_timeout=0.15,
                health_check_interval=30,
                decode_responses=True,
            )
            _redis_client_url = url
            return _redis_client
        except Exception as exc:  # pragma: no cover - dependency/configuration guard
            _disable_temporarily(exc)
            return None


def _generation_key(*, tenant_id: UUID | str, domain: str) -> str:
    return f"atc:query-cache:v1:g:{tenant_id}:{domain}"


def _identity_digest(identity: Any) -> str:
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def lookup(
    *,
    tenant_id: UUID | str,
    domain: str,
    identity: Any,
) -> CacheSlot:
    redis_client = _client()
    if redis_client is None:
        return CacheSlot(key=None)
    try:
        generation = redis_client.get(
            _generation_key(tenant_id=tenant_id, domain=domain)
        ) or "0"
        key = (
            f"atc:query-cache:v1:d:{tenant_id}:{domain}:{generation}:"
            f"{_identity_digest(identity)}"
        )
        raw = redis_client.get(key)
        if raw is None:
            return CacheSlot(key=key)
        try:
            return CacheSlot(key=key, value=json.loads(raw), hit=True)
        except (TypeError, ValueError):
            redis_client.delete(key)
            return CacheSlot(key=key)
    except Exception as exc:
        _disable_temporarily(exc)
        return CacheSlot(key=None)


def store(slot: CacheSlot, value: Any, *, ttl_seconds: int) -> None:
    if slot.key is None:
        return
    redis_client = _client()
    if redis_client is None:
        return
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        redis_client.set(slot.key, payload, ex=max(1, ttl_seconds))
    except Exception as exc:
        _disable_temporarily(exc)


def invalidate_versions(
    entries: Iterable[tuple[UUID | str, str]],
) -> None:
    unique_entries = sorted({(str(tenant_id), domain) for tenant_id, domain in entries})
    if not unique_entries:
        return
    redis_client = _client()
    if redis_client is None:
        return
    try:
        pipeline = redis_client.pipeline(transaction=False)
        for tenant_id, domain in unique_entries:
            pipeline.incr(_generation_key(tenant_id=tenant_id, domain=domain))
        pipeline.execute()
    except Exception as exc:
        _disable_temporarily(exc)


def mark_tenant_dirty(
    session: Session,
    *,
    tenant_id: UUID | str,
    domains: Iterable[str],
) -> None:
    pending = session.info.setdefault(_PENDING_INVALIDATIONS, set())
    pending.update((str(tenant_id), domain) for domain in domains)


_TABLE_DOMAINS: dict[str, frozenset[str]] = {
    # Catalog read models.
    "products": frozenset(
        {DOMAIN_CATALOG, DOMAIN_DASHBOARD, DOMAIN_INVENTORY, DOMAIN_METADATA}
    ),
    "skus": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD, DOMAIN_INVENTORY}),
    "product_images": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD}),
    "public_catalog_offers": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD}),
    "supplier_products": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD}),
    "suppliers": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD, DOMAIN_INVENTORY}),
    "source_files": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD}),
    "import_jobs": frozenset({DOMAIN_CATALOG, DOMAIN_DASHBOARD}),
    "product_categories": frozenset(
        {DOMAIN_CATALOG, DOMAIN_DASHBOARD, DOMAIN_INVENTORY, DOMAIN_METADATA}
    ),
    "product_tags": frozenset({DOMAIN_CATALOG, DOMAIN_METADATA}),
    "tenant_public_profiles": frozenset({DOMAIN_CATALOG, DOMAIN_METADATA}),
    # A catalog audit event is also emitted by bulk SQL updates, which lets the
    # event hook invalidate caches that ORM dirty tracking cannot see directly.
    "product_audit_events": frozenset(
        {DOMAIN_CATALOG, DOMAIN_DASHBOARD, DOMAIN_INVENTORY, DOMAIN_METADATA}
    ),
    # Dashboard workflow counters.
    "inquiries": frozenset({DOMAIN_DASHBOARD}),
    "inquiry_items": frozenset({DOMAIN_DASHBOARD}),
    "quotations": frozenset({DOMAIN_DASHBOARD}),
    "quotation_items": frozenset({DOMAIN_DASHBOARD}),
    "review_items": frozenset({DOMAIN_DASHBOARD}),
    # Inventory read models.
    "warehouses": frozenset({DOMAIN_INVENTORY}),
    "inventory_balances": frozenset({DOMAIN_INVENTORY}),
    "purchase_orders": frozenset({DOMAIN_INVENTORY}),
    "purchase_order_items": frozenset({DOMAIN_INVENTORY}),
    "sales_orders": frozenset({DOMAIN_INVENTORY}),
    "sales_order_items": frozenset({DOMAIN_INVENTORY}),
    "inventory_documents": frozenset({DOMAIN_INVENTORY}),
    "inventory_document_items": frozenset({DOMAIN_INVENTORY}),
    "inventory_movements": frozenset({DOMAIN_INVENTORY}),
}


@event.listens_for(Session, "before_flush")
def _collect_orm_invalidations(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    if not _enabled():
        return
    candidates = set(session.new).union(session.deleted)
    candidates.update(
        row
        for row in session.dirty
        if session.is_modified(row, include_collections=False)
    )
    for row in candidates:
        table_name = getattr(row, "__tablename__", "")
        domains = _TABLE_DOMAINS.get(table_name)
        tenant_id = getattr(row, "tenant_id", None)
        if domains and tenant_id is not None:
            mark_tenant_dirty(
                session,
                tenant_id=tenant_id,
                domains=domains,
            )


@event.listens_for(Session, "after_commit")
def _publish_invalidations(session: Session) -> None:
    pending = session.info.pop(_PENDING_INVALIDATIONS, set())
    invalidate_versions(pending)


@event.listens_for(Session, "after_rollback")
def _discard_invalidations(session: Session) -> None:
    session.info.pop(_PENDING_INVALIDATIONS, None)


def _reset_for_tests() -> None:
    global _redis_client, _redis_client_url, _redis_disabled_until
    with _CLIENT_LOCK:
        _redis_client = None
        _redis_client_url = None
        _redis_disabled_until = 0.0
