from __future__ import annotations

import pytest

from app.services import translation_rate_limit
from app.services.translation import (
    TranslationIdentity,
    TranslationProviderError,
)


@pytest.fixture(autouse=True)
def reset_translation_rate_limit() -> None:
    translation_rate_limit._reset_translation_rate_limit_for_tests()
    yield
    translation_rate_limit._reset_translation_rate_limit_for_tests()


def test_local_translation_rpm_waits_for_sliding_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    now = [100.0]
    waits: list[float] = []
    monkeypatch.setattr(
        translation_rate_limit.time,
        "monotonic",
        lambda: now[0],
    )

    def advance(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(translation_rate_limit.time, "sleep", advance)
    translation_rate_limit.configure_translation_requests_per_minute(2)

    translation_rate_limit.wait_for_translation_request_slot(2)
    translation_rate_limit.wait_for_translation_request_slot(2)
    translation_rate_limit.wait_for_translation_request_slot(2)

    assert waits == [60.0]


def test_redis_translation_rpm_waits_then_acquires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.responses = [[0, 1250, 1], [1, 0, 1]]

        def eval(self, *_args: object) -> list[int]:
            return self.responses.pop(0)

    waits: list[float] = []
    fake_redis = FakeRedis()
    monkeypatch.setenv("REDIS_URL", "redis://translation-test")
    monkeypatch.setattr(
        translation_rate_limit,
        "_client",
        lambda: fake_redis,
    )
    monkeypatch.setattr(translation_rate_limit.time, "sleep", waits.append)

    translation_rate_limit.wait_for_translation_request_slot(1)

    assert waits == [1.25]


def test_rate_limited_provider_preserves_provider_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)

    class Provider:
        identity = TranslationIdentity(provider="test", version="v1")
        translates_mixed_language_text = True

        def translate(
            self,
            text: str,
            *,
            source_locale: str,
            target_locale: str,
        ) -> str:
            return f"{source_locale}:{target_locale}:{text}"

    provider = translation_rate_limit.rate_limited_translation_provider(
        Provider(),
        requests_per_minute=30,
    )

    assert provider.identity == Provider.identity
    assert provider.translates_mixed_language_text is True
    assert provider.translate(
        "商品",
        source_locale="zh-CN",
        target_locale="en-US",
    ) == "zh-CN:en-US:商品"


def test_outbound_aware_provider_acquires_each_real_request_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acquired: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        translation_rate_limit,
        "wait_for_translation_request_slot",
        lambda rpm, *, use_configured_limit=True: acquired.append(
            (rpm, use_configured_limit)
        ),
    )

    class Provider:
        identity = TranslationIdentity(provider="test", version="v1")

        def install_request_gate(self, gate: object) -> None:
            self.gate = gate

        def translate(
            self,
            text: str,
            *,
            source_locale: str,
            target_locale: str,
        ) -> str:
            self.gate()
            self.gate()
            return text

    provider = translation_rate_limit.rate_limited_translation_provider(
        Provider(),
        requests_per_minute=7,
        synchronize_limit=False,
    )

    assert provider.translate(
        "商品",
        source_locale="zh-CN",
        target_locale="en-US",
    ) == "商品"
    assert acquired == [(7, False), (7, False)]


def test_translation_rpm_rejects_invalid_limits() -> None:
    with pytest.raises(TranslationProviderError):
        translation_rate_limit.normalized_translation_requests_per_minute(0)
    with pytest.raises(TranslationProviderError):
        translation_rate_limit.normalized_translation_requests_per_minute(
            10_001
        )
