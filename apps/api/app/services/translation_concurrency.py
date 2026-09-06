"""One shared realtime translation concurrency budget across API and workers."""
import logging
import os
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

from .translation import TranslationProviderError
from .translation_rate_limit import _client

log = logging.getLogger(__name__)
_KEY = "atc:translation-concurrency:v1:leases"
_LIMIT = "atc:translation-concurrency:v1:limit"
_LEASE_MS = 180_000
_condition = threading.Condition()
_active = 0
_local_limit = 1
_ACQUIRE = """
local tm = redis.call('TIME')
local now = tm[1] * 1000 + math.floor(tm[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
local limit = tonumber(redis.call('GET', KEYS[2])) or tonumber(ARGV[2])
if redis.call('ZCARD', KEYS[1]) >= limit then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]) + 1000)
return 1
"""
_RENEW = """
if not redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
local tm = redis.call('TIME')
local now = tm[1] * 1000 + math.floor(tm[2] / 1000)
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) + 1000)
return 1
"""


def configure(limit: int) -> int:
    global _local_limit
    limit = max(1, min(10, int(limit)))
    with _condition:
        _local_limit = limit
        _condition.notify_all()
    if os.getenv("REDIS_URL", "").strip():
        try:
            _client().set(_LIMIT, limit)
        except Exception as exc:
            raise TranslationProviderError("translation concurrency limiter is temporarily unavailable (Redis)") from exc
    return limit


@contextmanager
def request_slot(limit: int):
    global _active
    if not os.getenv("REDIS_URL", "").strip():
        with _condition:
            while _active >= _local_limit:
                _condition.wait(timeout=1)
            _active += 1
        try:
            yield
        finally:
            with _condition:
                _active -= 1
                _condition.notify_all()
        return
    token = uuid4().hex
    try:
        while not _client().eval(_ACQUIRE, 2, _KEY, _LIMIT, token, limit, _LEASE_MS):
            time.sleep(0.25)
    except Exception as exc:
        # Never fall back to separate per-process budgets when Redis is down.
        raise TranslationProviderError("translation concurrency limiter is temporarily unavailable (Redis)") from exc
    finished = threading.Event()
    lease_lost = threading.Event()

    def renew():
        while not finished.wait(30):
            try:
                if not _client().eval(_RENEW, 1, _KEY, token, _LEASE_MS):
                    lease_lost.set()
                    return
            except Exception:
                lease_lost.set()
                log.warning("translation concurrency lease renewal failed", exc_info=True)
                return

    heartbeat = threading.Thread(target=renew, daemon=True, name="translation-request-lease")
    heartbeat.start()
    try:
        yield
        if lease_lost.is_set():
            raise TranslationProviderError("translation concurrency lease was lost; request result requires retry")
    finally:
        finished.set()
        heartbeat.join(timeout=3)
        try:
            _client().zrem(_KEY, token)
        except Exception:
            log.warning("translation concurrency lease release failed; lease will expire", exc_info=True)
