from __future__ import annotations

from threading import Event, Thread

import pytest

from app.services import image_generation_rate_limit as limiter


@pytest.fixture(autouse=True)
def reset_limiter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    limiter._reset_image_generation_rate_limit_for_tests()
    yield
    limiter._reset_image_generation_rate_limit_for_tests()


def test_image_generation_defaults_and_bounds() -> None:
    assert limiter.DEFAULT_IMAGE_GENERATION_REQUESTS_PER_MINUTE == 6
    assert limiter.DEFAULT_IMAGE_GENERATION_CONCURRENCY == 3
    assert limiter.environment_image_generation_limits() == (6, 3)
    with pytest.raises(limiter.ImageGenerationRateLimitError):
        limiter.normalized_image_generation_requests_per_minute(0)
    with pytest.raises(limiter.ImageGenerationRateLimitError):
        limiter.normalized_image_generation_concurrency(33)


def test_local_rpm_waits_for_the_sliding_window(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    waits: list[float] = []
    monkeypatch.setattr(limiter.time, "monotonic", lambda: now[0])

    def advance(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(limiter.time, "sleep", advance)
    monkeypatch.setattr(
        limiter._local_condition,
        "wait",
        lambda timeout=None: advance(float(timeout or 0)),
    )
    for _ in range(3):
        with limiter.image_generation_request_slot(
            requests_per_minute=2,
            concurrency_limit=3,
            timeout_seconds=60,
        ):
            pass
    assert waits == [60.0]


def test_local_concurrency_waits_until_the_active_request_releases() -> None:
    started = Event()
    release = Event()
    acquired = Event()

    def hold_request() -> None:
        with limiter.image_generation_request_slot(
            requests_per_minute=100,
            concurrency_limit=1,
            timeout_seconds=60,
        ):
            started.set()
            release.wait(timeout=2)

    def wait_for_request() -> None:
        with limiter.image_generation_request_slot(
            requests_per_minute=100,
            concurrency_limit=1,
            timeout_seconds=60,
        ):
            acquired.set()

    holder = Thread(target=hold_request)
    waiter = Thread(target=wait_for_request)
    holder.start()
    assert started.wait(timeout=1)
    waiter.start()
    assert not acquired.wait(timeout=0.05)
    release.set()
    assert acquired.wait(timeout=1)
    holder.join(timeout=1)
    waiter.join(timeout=1)
