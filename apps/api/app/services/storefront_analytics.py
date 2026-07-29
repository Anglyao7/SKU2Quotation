from __future__ import annotations

import ipaddress
import logging
import os
from datetime import timedelta
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import Request

from ..database import SessionLocal, set_public_tenant_context
from ..model_mixins import utcnow
from ..repositories import storefront_analytics_repository as repository


logger = logging.getLogger(__name__)
_cleanup_lock = Lock()
_cleanup_scheduled_at: dict[UUID, float] = {}


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


def request_visitor_ip(request: Request) -> str:
    return normalize_ip_address(request.client.host if request.client else None)


def request_country_code(request: Request, *, visitor_ip: str) -> str:
    if os.getenv(
        "TRUST_CLOUDFLARE_VISITOR_HEADERS", "false"
    ).strip().casefold() not in {"1", "true", "yes"}:
        return "ZZ"
    connecting_ip = normalize_ip_address(request.headers.get("CF-Connecting-IP"))
    if connecting_ip == "0.0.0.0" or connecting_ip != visitor_ip:
        return "ZZ"
    country_code = request.headers.get("CF-IPCountry", "").strip().upper()
    if len(country_code) != 2 or not country_code.isascii() or not country_code.isalnum():
        return "ZZ"
    return country_code


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
