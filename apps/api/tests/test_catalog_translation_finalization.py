from __future__ import annotations

from threading import Lock
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import translation_memory
from app.services.translation import TranslationIdentity
from app.use_cases import catalog_translations


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Translator:
    identity = TranslationIdentity(provider="test", version="v1")


def test_translation_memory_honors_explicit_managed_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum_active = 0
    observed_batches: list[list[str]] = []
    lock = Lock()

    def translate_batch(_translator, values, **_kwargs):
        nonlocal active, maximum_active
        batch = list(values)
        with lock:
            observed_batches.append(batch)
            active += 1
            maximum_active = max(maximum_active, active)
        sleep(0.05)
        with lock:
            active -= 1
        return [f"translated-{value}" for value in batch]

    monkeypatch.setattr(
        translation_memory,
        "translate_catalog_values",
        translate_batch,
    )
    values = [f"规格-{index}" for index in range(6)]

    successes, failures = translation_memory._translate_uncached_values(
        _Translator(),
        values,
        source_locale="zh-CN",
        target_locale="en-US",
        batch_size=2,
        batch_characters=1_000,
        concurrency=2,
    )

    assert failures == {}
    assert successes == {
        value: f"translated-{value}" for value in values
    }
    assert {tuple(batch) for batch in observed_batches} == {
        tuple(values[0:2]),
        tuple(values[2:4]),
        tuple(values[4:6]),
    }
    assert maximum_active == 2


def test_language_pack_field_translation_resumes_from_its_own_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = ["规格甲", "规格乙"]
    translated_memory: set[str] = set()
    translated_requests: list[list[str]] = []
    pause_checks = 0

    monkeypatch.setattr(
        catalog_translations,
        "resolved_catalog_translation_batch_limits",
        lambda _session: (1, 100),
    )
    monkeypatch.setattr(
        catalog_translations,
        "resolved_catalog_translation_concurrency",
        lambda _session: 1,
    )
    monkeypatch.setattr(
        catalog_translations,
        "catalog_language_pack_translatable_values",
        lambda _rows: values,
    )
    monkeypatch.setattr(
        catalog_translations,
        "catalog_language_pack_translation_seed",
        lambda *_args, **_kwargs: {},
    )

    def availability(**_kwargs):
        missing = [value for value in values if value not in translated_memory]
        available = {
            value: f"translated-{value}" for value in translated_memory
        }
        return available, {"zh-CN": missing} if missing else {}

    def translate_values(**kwargs):
        assert kwargs["batch_size"] == 1
        assert kwargs["batch_characters"] == 100
        assert kwargs["concurrency"] == 1
        batch = list(kwargs["values"])
        translated_requests.append(batch)
        translated_memory.update(batch)
        return {value: f"translated-{value}" for value in batch}

    def pause_after_first_checkpoint(_session, _job):
        nonlocal pause_checks
        pause_checks += 1
        return pause_checks == 2

    monkeypatch.setattr(
        catalog_translations,
        "_batch_translation_availability",
        availability,
    )
    monkeypatch.setattr(
        catalog_translations,
        "translate_values_with_memory",
        translate_values,
    )
    monkeypatch.setattr(
        catalog_translations,
        "_pause_at_safe_checkpoint",
        pause_after_first_checkpoint,
    )

    job = SimpleNamespace(
        tenant_id=uuid4(),
        target_locale="en-US",
        batch_request_payload={},
        current_sku_id=None,
        current_sku_name=None,
        updated_at=None,
    )
    session = _Session()
    paused = catalog_translations._prepare_realtime_language_pack_values(
        session,
        job=job,
        translator=_Translator(),
        rows=[],
        sku_translations={},
        previous_payload=None,
        reuse_previous=False,
    )
    assert paused is True
    assert translated_requests == [["规格甲"]]
    assert catalog_translations._job_finalization_counts(job) == (2, 1)

    monkeypatch.setattr(
        catalog_translations,
        "_pause_at_safe_checkpoint",
        lambda _session, _job: False,
    )
    resumed = catalog_translations._prepare_realtime_language_pack_values(
        session,
        job=job,
        translator=_Translator(),
        rows=[],
        sku_translations={},
        previous_payload=None,
        reuse_previous=False,
    )
    assert resumed is False
    assert translated_requests == [["规格甲"], ["规格乙"]]
    assert catalog_translations._job_finalization_counts(job) == (2, 2)
    assert job.current_sku_name is None
