from __future__ import annotations

from collections import defaultdict

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services import rate_limit


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: defaultdict[str, int] = defaultdict(int)
        self.keys: list[str] = []

    def eval(
        self, _script: str, _key_count: int, key: str, window_seconds: int
    ) -> list[int]:
        self.keys.append(key)
        self.counts[key] += 1
        return [self.counts[key], window_seconds]


def _request(*, host: str = "203.0.113.42", forwarded_for: str = "198.51.100.8") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/sensitive",
            "raw_path": b"/sensitive",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", forwarded_for.encode("ascii"))],
            "client": (host, 43120),
            "server": ("api", 8000),
        }
    )


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://:secret@redis:6379/0")
    monkeypatch.setenv("AUTH_TOKEN_PEPPER", "P" * 48)
    monkeypatch.setattr(rate_limit, "_redis_client", fake)
    monkeypatch.setattr(
        rate_limit, "_redis_client_url", "redis://:secret@redis:6379/0"
    )
    return fake


def test_rate_limit_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    rate_limit.enforce_rate_limit(
        _request(), scope="auth-login", limit=1, window_seconds=60
    )


def test_rate_limit_uses_client_host_and_hashed_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install_fake(monkeypatch)
    request = _request()

    rate_limit.enforce_rate_limit(
        request,
        scope="auth-login",
        limit=1,
        window_seconds=60,
        token="authorization-code-secret",
    )
    with pytest.raises(HTTPException) as raised:
        rate_limit.enforce_rate_limit(
            _request(forwarded_for="192.0.2.99"),
            scope="auth-login",
            limit=1,
            window_seconds=60,
            token="authorization-code-secret",
        )

    assert raised.value.status_code == 429
    assert raised.value.headers["Retry-After"] == "60"
    assert len(set(fake.keys)) == 2
    assert all("authorization-code-secret" not in key for key in fake.keys)
    assert all("198.51.100.8" not in key and "192.0.2.99" not in key for key in fake.keys)


def test_rate_limit_fails_closed_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)

    class _UnavailableRedis:
        def eval(self, *_args: object) -> None:
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(rate_limit, "_redis_client", _UnavailableRedis())
    with pytest.raises(HTTPException) as raised:
        rate_limit.enforce_rate_limit(
            _request(), scope="public-quote-create", limit=10, window_seconds=60
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "RATE_LIMIT_UNAVAILABLE"
    assert raised.value.headers["Retry-After"] == "5"
