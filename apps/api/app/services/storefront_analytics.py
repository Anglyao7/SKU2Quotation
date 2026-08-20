from __future__ import annotations

import ipaddress
import logging
import os
from collections import OrderedDict
from datetime import timedelta
from threading import Lock
from time import monotonic
from uuid import UUID

import httpx
from fastapi import Request

from ..database import SessionLocal, set_public_tenant_context
from ..model_mixins import utcnow
from ..repositories import storefront_analytics_repository as repository


logger = logging.getLogger(__name__)
_cleanup_lock = Lock()
_cleanup_scheduled_at: dict[UUID, float] = {}
_geo_cache_lock = Lock()
_geo_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

DEFAULT_GEOLOCATION_URL = "https://ipwho.is/{ip}"


def raw_ip_retention_days() -> int:
    try:
        value = int(os.getenv("STOREFRONT_ANALYTICS_RAW_IP_RETENTION_DAYS", "60"))
    except ValueError:
        value = 60
    return max(7, min(value, 365))


def normalize_ip_address(value: str | None) -> str:
    try:
        parsed = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return "0.0.0.0"
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return parsed.compressed


def _valid_country_code(value: object) -> str | None:
    normalized = str(value or "").strip().upper()
    # Cloudflare uses T1 for Tor traffic. Keep that useful classification while
    # rejecting arbitrary values from a proxy or third-party response.
    if normalized == "T1" or (len(normalized) == 2 and normalized.isalpha()):
        return normalized
    return None


def _geo_cache_seconds() -> int:
    try:
        value = int(os.getenv("STOREFRONT_ANALYTICS_GEO_CACHE_SECONDS", "86400"))
    except ValueError:
        value = 86400
    return max(300, min(value, 604800))


def _geo_cache_max_entries() -> int:
    try:
        value = int(os.getenv("STOREFRONT_ANALYTICS_GEO_CACHE_MAX_ENTRIES", "8192"))
    except ValueError:
        value = 8192
    return max(128, min(value, 100_000))


def _geo_timeout_seconds() -> float:
    try:
        value = float(
            os.getenv("STOREFRONT_ANALYTICS_GEO_TIMEOUT_SECONDS", "1.5")
        )
    except ValueError:
        value = 1.5
    return max(0.2, min(value, 5.0))


def _geolocation_url(ip_address: str) -> str:
    configured = os.getenv(
        "STOREFRONT_ANALYTICS_GEOLOCATION_URL", DEFAULT_GEOLOCATION_URL
    ).strip()
    if not configured:
        configured = DEFAULT_GEOLOCATION_URL
    if "{ip}" in configured:
        return configured.replace("{ip}", ip_address)
    return f"{configured.rstrip('/')}/{ip_address}"


def _cache_country_code(ip_address: str, country_code: str) -> None:
    with _geo_cache_lock:
        _geo_cache[ip_address] = (monotonic(), country_code)
        _geo_cache.move_to_end(ip_address)
        while len(_geo_cache) > _geo_cache_max_entries():
            _geo_cache.popitem(last=False)


def _cached_country_code(ip_address: str) -> str | None:
    with _geo_cache_lock:
        entry = _geo_cache.get(ip_address)
        if entry is None:
            return None
        cached_at, country_code = entry
        if monotonic() - cached_at >= _geo_cache_seconds():
            _geo_cache.pop(ip_address, None)
            return None
        _geo_cache.move_to_end(ip_address)
        return country_code


def lookup_country_code(ip_address: str) -> str:
    """Resolve a public IP to an ISO country code with a bounded best-effort lookup.

    Cloudflare's edge header remains the preferred source when trusted. This
    fallback fixes direct-origin, local-network, and non-Cloudflare requests
    without making geolocation a hard dependency for recording a view.
    """

    normalized_ip = normalize_ip_address(ip_address)
    if normalized_ip == "0.0.0.0":
        return "ZZ"
    try:
        parsed = ipaddress.ip_address(normalized_ip)
    except ValueError:
        return "ZZ"
    if not parsed.is_global:
        return "ZZ"

    cached = _cached_country_code(normalized_ip)
    if cached is not None:
        return cached

    country_code = "ZZ"
    try:
        response = httpx.get(
            _geolocation_url(normalized_ip),
            headers={"Accept": "application/json"},
            timeout=_geo_timeout_seconds(),
            follow_redirects=True,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            # ipwho.is returns ``success: false`` for invalid/private inputs.
            if payload.get("success", True) is not False:
                country_code = _valid_country_code(
                    payload.get("country_code") or payload.get("countryCode")
                ) or "ZZ"
    except Exception as exc:  # pragma: no cover - provider/network dependent
        logger.info(
            "IP country provider unavailable: %s",
            type(exc).__name__,
        )

    # Cache negative results briefly as well, otherwise a provider outage could
    # turn every view from one visitor into a new outbound request.
    _cache_country_code(normalized_ip, country_code)
    return country_code


def request_visitor_ip(request: Request) -> str:
    return normalize_ip_address(request.client.host if request.client else None)


def request_country_code(request: Request, *, visitor_ip: str) -> str:
    trust_cloudflare = os.getenv(
        "TRUST_CLOUDFLARE_VISITOR_HEADERS", "false"
    ).strip().casefold() in {"1", "true", "yes"}
    if trust_cloudflare:
        connecting_ip = normalize_ip_address(request.headers.get("CF-Connecting-IP"))
        if connecting_ip != "0.0.0.0" and connecting_ip == visitor_ip:
            country_code = _valid_country_code(request.headers.get("CF-IPCountry"))
            if country_code:
                return country_code
    return lookup_country_code(visitor_ip)


def mark_cleanup_scheduled(tenant_id: UUID) -> bool:
    """Allow one raw-IP retention cleanup per tenant and API process every 6h."""

    now = monotonic()
    with _cleanup_lock:
        previous = _cleanup_scheduled_at.get(tenant_id)
        if previous is not None and now - previous < 6 * 60 * 60:
            return False
        _cleanup_scheduled_at[tenant_id] = now
        return True


def cleanup_expired_raw_events(tenant_id: UUID) -> None:
    cutoff = utcnow() - timedelta(days=raw_ip_retention_days())
    try:
        with SessionLocal() as session:
            set_public_tenant_context(session, tenant_id=tenant_id)
            deleted = repository.delete_events_before(
                session,
                tenant_id=tenant_id,
                cutoff=cutoff,
            )
            session.commit()
        if deleted:
            logger.info(
                "storefront analytics raw-IP retention removed %s events for tenant %s",
                deleted,
                tenant_id,
            )
    except Exception:
        logger.exception(
            "storefront analytics raw-IP retention failed for tenant %s",
            tenant_id,
        )
