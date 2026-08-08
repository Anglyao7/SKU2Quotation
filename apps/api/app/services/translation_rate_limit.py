"""Platform-wide outbound request pacing for translation providers."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any
from uuid import uuid4

from .translation import TranslationProvider, TranslationProviderError


logger = logging.getLogger(__name__)
DEFAULT_TRANSLATION_REQUESTS_PER_MINUTE = 60
MAX_TRANSLATION_REQUESTS_PER_MINUTE = 10_000
_WINDOW_MILLISECONDS = 60_000
_REQUESTS_KEY = "atc:translation-rpm:v1:requests"
_CONFIG_KEY = "atc:translation-rpm:v1:configured-limit"
_SLIDING_WINDOW_SCRIPT = """
local current_time = redis.call("TIME")
local now = current_time[1] * 1000 + math.floor(current_time[2] / 1000)
local window = tonumber(ARGV[1])
local fallback_limit = tonumber(ARGV[2])
local member = ARGV[3]
local configured_limit = tonumber(redis.call("GET", KEYS[2]))
local limit = configured_limit or fallback_limit
if limit == nil or limit < 1 then
  limit = fallback_limit
end

redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", now - window)
local count = redis.call("ZCARD", KEYS[1])
if count < limit then
  redis.call("ZADD", KEYS[1], now, member)
  redis.call("PEXPIRE", KEYS[1], window + 1000)
  return {1, 0, limit}
end

local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
local retry_after = window
if oldest[2] ~= nil then
  retry_after = math.max(1, tonumber(oldest[2]) + window - now)
end
return {0, retry_after, limit}
"""

_redis_client: Any | None = None
_redis_client_url: str | None = None
_local_lock = threading.Lock()
_local_requests: deque[float] = deque()
_local_requests_per_minute = DEFAULT_TRANSLATION_REQUESTS_PER_MINUTE


def normalized_translation_requests_per_minute(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TranslationProviderError(
            "translation requests per minute must be an integer"
        ) from exc
    if normalized < 1 or normalized > MAX_TRANSLATION_REQUESTS_PER_MINUTE:
        raise TranslationProviderError(
            "translation requests per minute must be between 1 and 10000"
        )
    return normalized


def environment_translation_requests_per_minute() -> int:
    raw = os.getenv(
        "TRANSLATION_REQUESTS_PER_MINUTE",
        str(DEFAULT_TRANSLATION_REQUESTS_PER_MINUTE),
    ).strip()
    try:
        return normalized_translation_requests_per_minute(int(raw))
    except (TypeError, ValueError, TranslationProviderError) as exc:
        raise TranslationProviderError(
            "TRANSLATION_REQUESTS_PER_MINUTE must be an integer between 1 and 10000"
        ) from exc


def _client() -> Any:
    global _redis_client, _redis_client_url
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is not configured")
    if _redis_client is None or _redis_client_url != url:
        try:
            from redis import Redis
        except ImportError as exc:  # pragma: no cover - production contract
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


def configure_translation_requests_per_minute(value: int) -> int:
    """Publish the current limit for existing and future provider wrappers."""

    normalized = normalized_translation_requests_per_minute(value)
    global _local_requests_per_minute
    with _local_lock:
        _local_requests_per_minute = normalized

    if os.getenv("REDIS_URL", "").strip():
        try:
            _client().set(_CONFIG_KEY, normalized)
        except Exception:
            # Persistence in translation_provider_settings remains authoritative.
            # A later provider resolution will synchronize Redis again.
            logger.warning(
                "could not synchronize translation RPM limit to Redis",
                exc_info=True,
            )
    return normalized


def _wait_for_local_slot(
    fallback_limit: int,
    *,
    use_configured_limit: bool,
) -> None:
    while True:
        with _local_lock:
            limit = (
                _local_requests_per_minute
                if use_configured_limit
                else fallback_limit
            )
            now = time.monotonic()
            threshold = now - 60.0
            while _local_requests and _local_requests[0] <= threshold:
                _local_requests.popleft()
            if len(_local_requests) < limit:
                _local_requests.append(now)
                return
            wait_seconds = max(0.001, 60.0 - (now - _local_requests[0]))
        time.sleep(wait_seconds)


def _wait_for_redis_slot(fallback_limit: int) -> None:
    while True:
        try:
            result = _client().eval(
                _SLIDING_WINDOW_SCRIPT,
                2,
                _REQUESTS_KEY,
                _CONFIG_KEY,
                _WINDOW_MILLISECONDS,
                fallback_limit,
                uuid4().hex,
            )
            admitted = bool(int(result[0]))
            retry_after_ms = max(1, int(result[1]))
        except Exception as exc:
            raise TranslationProviderError(
                "translation RPM limiter is temporarily unavailable"
            ) from exc
        if admitted:
            return
        time.sleep(min(retry_after_ms / 1000.0, 60.0))


def wait_for_translation_request_slot(
    requests_per_minute: int,
    *,
    use_configured_limit: bool = True,
) -> None:
    fallback_limit = normalized_translation_requests_per_minute(
        requests_per_minute
    )
    if os.getenv("REDIS_URL", "").strip():
        _wait_for_redis_slot(fallback_limit)
        return
    _wait_for_local_slot(
        fallback_limit,
        use_configured_limit=use_configured_limit,
    )


class RateLimitedTranslationProvider:
    """A transparent provider wrapper sharing one platform RPM budget."""

    def __init__(
        self,
        provider: TranslationProvider,
        *,
        requests_per_minute: int,
        synchronize_limit: bool,
    ) -> None:
        self._provider = provider
        self._use_configured_limit = synchronize_limit
        self.requests_per_minute = (
            configure_translation_requests_per_minute(requests_per_minute)
            if synchronize_limit
            else normalized_translation_requests_per_minute(requests_per_minute)
        )
        self.identity = provider.identity
        self.translates_mixed_language_text = bool(
            getattr(provider, "translates_mixed_language_text", False)
        )
        install_request_gate = getattr(provider, "install_request_gate", None)
        self._provider_gates_outbound_requests = callable(install_request_gate)
        if self._provider_gates_outbound_requests:
            install_request_gate(self._acquire_request_slot)

    def _acquire_request_slot(self) -> None:
        wait_for_translation_request_slot(
            self.requests_per_minute,
            use_configured_limit=self._use_configured_limit,
        )

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        if (
            text
            and source_locale != target_locale
            and not self._provider_gates_outbound_requests
        ):
            self._acquire_request_slot()
        return self._provider.translate(
            text,
            source_locale=source_locale,
            target_locale=target_locale,
        )


def rate_limited_translation_provider(
    provider: TranslationProvider,
    *,
    requests_per_minute: int,
    synchronize_limit: bool = True,
) -> TranslationProvider:
    if isinstance(provider, RateLimitedTranslationProvider):
        return provider
    return RateLimitedTranslationProvider(
        provider,
        requests_per_minute=requests_per_minute,
        synchronize_limit=synchronize_limit,
    )


def _reset_translation_rate_limit_for_tests() -> None:
    global _redis_client, _redis_client_url, _local_requests_per_minute
    _redis_client = None
    _redis_client_url = None
    with _local_lock:
        _local_requests.clear()
        _local_requests_per_minute = DEFAULT_TRANSLATION_REQUESTS_PER_MINUTE
