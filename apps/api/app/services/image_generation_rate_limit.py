"""Outbound pacing and concurrency limits for the image-generation provider.

The limits are deliberately enforced immediately before the upstream request,
not only when an enhancement task is created.  That keeps direct callers and
future image workflows inside the same budget.  Redis is used when available
so multiple API processes share the budget; a process-local gate remains a
safe development fallback when Redis is not configured or temporarily down.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from uuid import uuid4


logger = logging.getLogger(__name__)

DEFAULT_IMAGE_GENERATION_REQUESTS_PER_MINUTE = 6
MAX_IMAGE_GENERATION_REQUESTS_PER_MINUTE = 10_000
DEFAULT_IMAGE_GENERATION_CONCURRENCY = 3
MAX_IMAGE_GENERATION_CONCURRENCY = 32
_WINDOW_SECONDS = 60.0
_WINDOW_MILLISECONDS = 60_000
_RPM_KEY = "atc:image-generation:v1:rpm"
_CONCURRENCY_KEY = "atc:image-generation:v1:concurrency"

_RPM_SCRIPT = """
local current_time = redis.call("TIME")
local now = current_time[1] * 1000 + math.floor(current_time[2] / 1000)
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local member = ARGV[3]
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", now - window)
local count = redis.call("ZCARD", KEYS[1])
if count < limit then
  redis.call("ZADD", KEYS[1], now, member)
  redis.call("PEXPIRE", KEYS[1], window + 1000)
  return {1, 0}
end
local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
local retry_after = window
if oldest[2] ~= nil then
  retry_after = math.max(1, tonumber(oldest[2]) + window - now)
end
return {0, retry_after}
"""

_CONCURRENCY_SCRIPT = """
local current_time = redis.call("TIME")
local now = current_time[1] * 1000 + math.floor(current_time[2] / 1000)
local limit = tonumber(ARGV[1])
local lease_ms = tonumber(ARGV[2])
local member = ARGV[3]
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", now)
local count = redis.call("ZCARD", KEYS[1])
if count < limit then
  redis.call("ZADD", KEYS[1], now + lease_ms, member)
  redis.call("PEXPIRE", KEYS[1], lease_ms + 1000)
  return {1, 0}
end
local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
local retry_after = lease_ms
if oldest[2] ~= nil then
  retry_after = math.max(1, tonumber(oldest[2]) - now)
end
return {0, retry_after}
"""

_RELEASE_SCRIPT = "redis.call('ZREM', KEYS[1], ARGV[1]); return 1"

_redis_client: Any | None = None
_redis_client_url: str | None = None
_redis_lock = threading.Lock()

_local_condition = threading.Condition()
_local_active = 0
_local_requests: deque[float] = deque()


class ImageGenerationRateLimitError(ValueError):
    """Raised when the shared limiter cannot be reached."""


def normalized_image_generation_requests_per_minute(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ImageGenerationRateLimitError(
            "image generation requests per minute must be an integer"
        ) from exc
    if not 1 <= normalized <= MAX_IMAGE_GENERATION_REQUESTS_PER_MINUTE:
        raise ImageGenerationRateLimitError(
            "image generation requests per minute must be between 1 and 10000"
        )
    return normalized


def normalized_image_generation_concurrency(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ImageGenerationRateLimitError(
            "image generation concurrency must be an integer"
        ) from exc
    if not 1 <= normalized <= MAX_IMAGE_GENERATION_CONCURRENCY:
        raise ImageGenerationRateLimitError(
            "image generation concurrency must be between 1 and 32"
        )
    return normalized


def environment_image_generation_limits() -> tuple[int, int]:
    """Read optional environment defaults for installations without a row."""

    raw_rpm = os.getenv(
        "AGNES_IMAGE_GENERATION_REQUESTS_PER_MINUTE",
        str(DEFAULT_IMAGE_GENERATION_REQUESTS_PER_MINUTE),
    ).strip()
    raw_concurrency = os.getenv(
        "AGNES_IMAGE_GENERATION_CONCURRENCY_LIMIT",
        str(DEFAULT_IMAGE_GENERATION_CONCURRENCY),
    ).strip()
    try:
        rpm = normalized_image_generation_requests_per_minute(int(raw_rpm))
        concurrency = normalized_image_generation_concurrency(int(raw_concurrency))
    except (TypeError, ValueError, ImageGenerationRateLimitError) as exc:
        raise ImageGenerationRateLimitError(
            "image generation limits must be valid positive integers"
        ) from exc
    return rpm, concurrency


def _client() -> Any:
    global _redis_client, _redis_client_url
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        raise ImageGenerationRateLimitError("REDIS_URL is not configured")
    with _redis_lock:
        if _redis_client is not None and _redis_client_url == url:
            return _redis_client
        try:
            from redis import Redis
        except ImportError as exc:  # pragma: no cover - production image contract
            raise ImageGenerationRateLimitError("Redis client is unavailable") from exc
        try:
            _redis_client = Redis.from_url(
                url,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                health_check_interval=30,
                decode_responses=False,
            )
            _redis_client_url = url
            return _redis_client
        except Exception as exc:
            _redis_client = None
            _redis_client_url = None
            raise ImageGenerationRateLimitError(
                "image generation limiter is temporarily unavailable"
            ) from exc


def _redis_wait_for_rpm(client: Any, rpm: int, member: str) -> None:
    while True:
        try:
            result = client.eval(
                _RPM_SCRIPT,
                1,
                _RPM_KEY,
                _WINDOW_MILLISECONDS,
                rpm,
                member,
            )
        except Exception as exc:
            raise ImageGenerationRateLimitError(
                "image generation limiter is temporarily unavailable"
            ) from exc
        if bool(int(result[0])):
            return
        retry_after = max(1, int(result[1]))
        time.sleep(min(retry_after / 1000.0, _WINDOW_SECONDS))


def _redis_wait_for_concurrency(
    client: Any,
    concurrency: int,
    lease_ms: int,
    member: str,
) -> None:
    while True:
        try:
            result = client.eval(
                _CONCURRENCY_SCRIPT,
                1,
                _CONCURRENCY_KEY,
                concurrency,
                lease_ms,
                member,
            )
        except Exception as exc:
            raise ImageGenerationRateLimitError(
                "image generation limiter is temporarily unavailable"
            ) from exc
        if bool(int(result[0])):
            return
        retry_after = max(1, int(result[1]))
        time.sleep(min(retry_after / 1000.0, _WINDOW_SECONDS))


def _redis_release(client: Any, key: str, member: str) -> None:
    try:
        client.eval(_RELEASE_SCRIPT, 1, key, member)
    except Exception:
        logger.warning("could not release image generation limiter lease", exc_info=True)


@dataclass(slots=True)
class _LocalSlot:
    released: bool = False


@dataclass(slots=True)
class _RedisSlot:
    client: Any
    rpm_member: str
    concurrency_member: str
    released: bool = False


def _purge_local_requests(now: float) -> None:
    threshold = now - _WINDOW_SECONDS
    while _local_requests and _local_requests[0] <= threshold:
        _local_requests.popleft()


def _acquire_local(rpm: int, concurrency: int) -> _LocalSlot:
    global _local_active
    while True:
        with _local_condition:
            now = time.monotonic()
            _purge_local_requests(now)
            if _local_active < concurrency and len(_local_requests) < rpm:
                _local_active += 1
                _local_requests.append(now)
                return _LocalSlot()
            waits: list[float] = []
            if _local_active >= concurrency:
                waits.append(0.25)
            if len(_local_requests) >= rpm:
                waits.append(max(0.001, _WINDOW_SECONDS - (now - _local_requests[0])))
            _local_condition.wait(timeout=min(waits) if waits else 0.25)


def _release_local(slot: _LocalSlot) -> None:
    global _local_active
    with _local_condition:
        if slot.released:
            return
        slot.released = True
        _local_active = max(0, _local_active - 1)
        _local_condition.notify_all()


def _acquire_redis(rpm: int, concurrency: int, timeout_seconds: int) -> _RedisSlot:
    client = _client()
    token = uuid4().hex
    rpm_member = f"{token}:rpm"
    concurrency_member = f"{token}:concurrency"
    _redis_wait_for_rpm(client, rpm, rpm_member)
    try:
        _redis_wait_for_concurrency(
            client,
            concurrency,
            max(1_000, (int(timeout_seconds) + 30) * 1_000),
            concurrency_member,
        )
    except Exception:
        _redis_release(client, _RPM_KEY, rpm_member)
        raise
    return _RedisSlot(client, rpm_member, concurrency_member)


@contextmanager
def image_generation_request_slot(
    *,
    requests_per_minute: int,
    concurrency_limit: int,
    timeout_seconds: int,
) -> Iterator[None]:
    """Wait for one provider request slot and release it on every exit path."""

    rpm = normalized_image_generation_requests_per_minute(requests_per_minute)
    concurrency = normalized_image_generation_concurrency(concurrency_limit)
    slot: _LocalSlot | _RedisSlot
    if os.getenv("REDIS_URL", "").strip():
        try:
            slot = _acquire_redis(rpm, concurrency, timeout_seconds)
        except ImageGenerationRateLimitError:
            # A limiter outage must not turn a configured provider into a
            # permanent outage.  The local gate still protects this process;
            # the next request will retry Redis and restore shared limiting.
            logger.warning("falling back to the local image generation limiter", exc_info=True)
            slot = _acquire_local(rpm, concurrency)
    else:
        slot = _acquire_local(rpm, concurrency)

    try:
        yield
    finally:
        if isinstance(slot, _LocalSlot):
            _release_local(slot)
        elif not slot.released:
            slot.released = True
            # RPM entries intentionally remain in the rolling Redis window;
            # removing them here would turn the limit into a concurrency-only
            # counter.  They expire naturally after sixty seconds.
            _redis_release(slot.client, _CONCURRENCY_KEY, slot.concurrency_member)


def _reset_image_generation_rate_limit_for_tests() -> None:
    """Reset process state between tests without touching Redis data."""

    global _redis_client, _redis_client_url, _local_active
    _redis_client = None
    _redis_client_url = None
    with _local_condition:
        _local_active = 0
        _local_requests.clear()
        _local_condition.notify_all()
