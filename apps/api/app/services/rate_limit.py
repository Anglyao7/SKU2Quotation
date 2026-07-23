"""Redis-backed, fail-closed rate limits for security-sensitive HTTP routes."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException, Request, status


_FIXED_WINDOW_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
return {current, ttl}
"""
_SAFE_SCOPE = re.compile(r"[^a-z0-9:_-]+")
_redis_client: Any | None = None
_redis_client_url: str | None = None


def rate_limits_enabled() -> bool:
    return os.getenv("RATE_LIMIT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configured_limit(name: str, default: int, *, maximum: int = 100_000) -> int:
    """Read a positive integer limit while keeping unsafe values bounded."""

    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(value, maximum))


def _client() -> Any:
    global _redis_client, _redis_client_url
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is not configured")
    if _redis_client is None or _redis_client_url != url:
        try:
            from redis import Redis
        except ImportError as exc:  # pragma: no cover - production image contract
            raise RuntimeError("Redis client is unavailable") from exc
        _redis_client = Redis.from_url(
            url,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
            decode_responses=False,
        )
        _redis_client_url = url
    return _redis_client


def _identity_digest(kind: str, value: str) -> str:
    pepper = (
        os.getenv("RATE_LIMIT_KEY_PEPPER", "").strip()
        or os.getenv("AUTH_TOKEN_PEPPER", "").strip()
        or "development-only-rate-limit-key"
    )
    return hmac.new(
        pepper.encode("utf-8"),
        f"{kind}\0{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _key(*, scope: str, kind: str, value: str) -> str:
    safe_scope = _SAFE_SCOPE.sub("-", scope.strip().lower())[:100] or "unknown"
    return f"atc:rate-limit:v1:{safe_scope}:{kind}:{_identity_digest(kind, value)}"


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "RATE_LIMIT_UNAVAILABLE",
            "message": "Request protection is temporarily unavailable.",
        },
        headers={"Retry-After": "5", "Cache-Control": "no-store"},
    )


def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    token: str | None = None,
    additional_subjects: Iterable[tuple[str, str]] = (),
) -> None:
    """Consume an IP bucket and, when supplied, independent credential buckets.

    ``request.client.host`` is intentionally the sole IP source. In production,
    Uvicorn accepts forwarded headers only from the pinned reverse-proxy subnet,
    so callers cannot select their own bucket with an arbitrary header.
    """

    if not rate_limits_enabled():
        return

    host = request.client.host if request.client else "unknown"
    subjects: list[tuple[str, str]] = [("ip", host)]
    if token:
        subjects.append(("token", token))
    subjects.extend((kind, value) for kind, value in additional_subjects if value)

    retry_after = 0
    try:
        redis_client = _client()
        for kind, value in subjects:
            result = redis_client.eval(
                _FIXED_WINDOW_SCRIPT,
                1,
                _key(scope=scope, kind=kind, value=value),
                window_seconds,
            )
            count, ttl = int(result[0]), int(result[1])
            if count > limit:
                retry_after = max(retry_after, ttl if ttl > 0 else window_seconds)
    except Exception as exc:
        raise _unavailable() from exc

    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "RATE_LIMITED",
                "message": "Too many requests. Please retry later.",
            },
            headers={
                "Retry-After": str(max(1, retry_after)),
                "Cache-Control": "no-store",
            },
        )


def _reset_client_for_tests() -> None:
    global _redis_client, _redis_client_url
    _redis_client = None
    _redis_client_url = None
