from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.translation import TranslationIdentity
from app.use_cases import catalog_translations


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Translator:
    identity = TranslationIdentity(provider="test", version="v1")


def test_language_pack_field_translation_resumes_from_its_own_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = ["规格甲", "规格乙"]
    translated_memory: set[str] = set()
    translated_requests: list[list[str]] = []
    pause_checks = 0

    monkeypatch.setenv("PUBLIC_LIVE_TRANSLATION_BATCH_SIZE", "1")
    monkeypatch.setenv("PUBLIC_LIVE_TRANSLATION_BATCH_CHARACTERS", "100")
    monkeypatch.setenv("PUBLIC_LIVE_TRANSLATION_CONCURRENCY", "1")
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
