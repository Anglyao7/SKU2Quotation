from __future__ import annotations

from threading import Lock
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.catalog_translation_schemas import CatalogTranslationJobStartRequest
from app.domain.errors import ApplicationError
from app.services.auth.dependencies import RequestContext
from app.services import translation_memory
from app.services.translation import TranslationIdentity, TranslationProviderError
from app.use_cases import catalog_translations


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Translator:
    identity = TranslationIdentity(provider="test", version="v1")


def test_qwen_small_remainder_switches_to_two_realtime_waves() -> None:
    requests = [
        {"custom_id": f"request-{index}", "values": [str(index)]}
        for index in range(14)
    ]

    assert catalog_translations._qwen_requests_fit_realtime_tail(
        requests,
        concurrency=10,
    )
    assert not catalog_translations._qwen_requests_fit_realtime_tail(
        requests + requests[:7],
        concurrency=10,
    )
    assert not catalog_translations._qwen_requests_fit_realtime_tail(
        [],
        concurrency=10,
    )


def test_translation_administration_requires_platform_admin() -> None:
    with pytest.raises(ApplicationError) as caught:
        catalog_translations._require_platform_admin(
            SimpleNamespace(is_platform_admin=False)
        )

    assert caught.value.code == "PLATFORM_ADMIN_REQUIRED"


def test_platform_admin_can_scope_translation_to_a_merchant_without_impersonation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_tenant_id = uuid4()
    merchant_tenant_id = uuid4()
    admin_organization_id = uuid4()
    merchant_organization_id = uuid4()
    context = RequestContext(
        user_id=uuid4(),
        membership_id=uuid4(),
        tenant_id=admin_tenant_id,
        organization_id=admin_organization_id,
        locale="zh-CN",
        permission_version=1,
        permissions=frozenset({"product.view", "product.edit"}),
        is_platform_admin=True,
    )
    tenant = SimpleNamespace(
        id=merchant_tenant_id,
        organization_id=merchant_organization_id,
        deleted_at=None,
    )
    session = SimpleNamespace(get=lambda _model, _tenant_id: tenant)
    bindings: list[tuple[object, object, object]] = []
    monkeypatch.setattr(
        catalog_translations,
        "set_request_context",
        lambda _session, *, organization_id, tenant_id, user_id: bindings.append(
            (organization_id, tenant_id, user_id)
        ),
    )

    with catalog_translations.platform_admin_translation_scope(
        session,
        context=context,
        tenant_id=merchant_tenant_id,
    ) as (scoped_context, requester_membership_id):
        assert scoped_context.tenant_id == merchant_tenant_id
        assert scoped_context.organization_id == merchant_organization_id
        assert scoped_context.is_platform_admin is True
        assert requester_membership_id is None

    assert bindings == [
        (merchant_organization_id, merchant_tenant_id, context.user_id),
        (admin_organization_id, admin_tenant_id, context.user_id),
    ]


def test_translation_buttons_can_explicitly_select_execution_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    monkeypatch.setattr(
        catalog_translations,
        "catalog_translation_execution_mode",
        lambda _session: "QWEN_BATCH",
    )

    incremental = CatalogTranslationJobStartRequest(
        target_locale="es",
        mode="INCREMENTAL",
        execution_mode="REALTIME",
    )
    configured_default = CatalogTranslationJobStartRequest(
        target_locale="es",
        mode="INCREMENTAL",
    )

    assert catalog_translations._requested_job_execution_mode(
        session,
        incremental,
    ) == "REALTIME"
    assert catalog_translations._requested_job_execution_mode(
        session,
        configured_default,
    ) == "QWEN_BATCH"


def test_only_explicit_batch_rebuild_adopts_hidden_checkpoint() -> None:
    incremental = CatalogTranslationJobStartRequest(
        target_locale="en-US",
        mode="INCREMENTAL",
        execution_mode="REALTIME",
    )
    full_rebuild = CatalogTranslationJobStartRequest(
        target_locale="en-US",
        mode="FULL_REBUILD",
        execution_mode="QWEN_BATCH",
        confirm_full_rebuild=True,
    )

    assert catalog_translations._should_resume_hidden_checkpoint(
        incremental,
        execution_mode="REALTIME",
    ) is False
    assert catalog_translations._should_resume_hidden_checkpoint(
        full_rebuild,
        execution_mode="QWEN_BATCH",
    ) is True


def test_zero_request_batch_does_not_report_full_corpus_as_pending() -> None:
    job = SimpleNamespace(
        batch_request_payload={
            "requests": [],
            "value_count": 27_927,
            "qwen_batch_progress": {
                "total_values": 0,
                "processed_values": 0,
            },
        }
    )

    assert catalog_translations._job_qwen_batch_counts(job) == (0, 0)


def test_language_package_manifest_uses_same_origin_download() -> None:
    pack = SimpleNamespace(
        public_url=(
            "https://resources.example.test/translations/tenant/en-US/"
            "catalog-v7.json.gz"
        ),
        target_locale="en-US",
        version=7,
    )

    assert catalog_translations._language_pack_download_url(
        pack,
        tenant_slug="yoyo-pets",
    ) == "/api/store/yoyo-pets/language-packages/en-US/versions/7"


def test_switching_mode_preserves_and_releases_a_paused_checkpoint() -> None:
    session = _Session()
    checkpoint = {"requests": [{"custom_id": "kept"}]}
    job = SimpleNamespace(
        status="PAUSED",
        stage="PAUSED",
        execution_mode="QWEN_BATCH",
        pause_requested_at=None,
        completed_at=None,
        error_message=None,
        batch_request_payload=checkpoint,
    )

    replaced = catalog_translations._supersede_paused_job_for_mode(
        session,
        job=job,
        execution_mode="REALTIME",
        explicitly_requested=True,
    )

    assert replaced is True
    assert job.status == "FAILED"
    assert job.stage == "FAILED"
    assert job.batch_request_payload is checkpoint
    assert "断点" in job.error_message
    assert session.commits == 1


def test_empty_materialized_locale_uses_fast_exact_status_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = SimpleNamespace(slug="tenant")

    class _StatusSession:
        def get(self, _model, _identity):
            return tenant

    session = _StatusSession()
    monkeypatch.setattr(
        catalog_translations,
        "catalog_translation_execution_mode",
        lambda _session: "REALTIME",
    )
    monkeypatch.setattr(
        catalog_translations,
        "translation_provider_is_configured",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        catalog_translations.translation_repository,
        "language_pack",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        catalog_translations.translation_repository,
        "count_translations",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        catalog_translations.translation_repository,
        "available_target_locales",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        catalog_translations.translation_repository,
        "available_language_pack_locales",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        catalog_translations.public_catalog_repository,
        "count_public_catalog_rows",
        lambda *_args, **_kwargs: 11_863,
    )
    monkeypatch.setattr(
        catalog_translations,
        "language_package_storage_status",
        lambda: SimpleNamespace(configured=True, fingerprint="storage"),
    )
    monkeypatch.setattr(
        catalog_translations,
        "_all_rows",
        lambda *_args, **_kwargs: pytest.fail("full catalog should not load"),
    )
    monkeypatch.setattr(
        catalog_translations,
        "_status_rows",
        lambda *_args, **_kwargs: pytest.fail("catalog rows should not load"),
    )
    monkeypatch.setattr(
        catalog_translations,
        "latest_translation_job",
        lambda *_args, **_kwargs: pytest.fail("history should load separately"),
    )

    result = catalog_translations.get_translation_status(
        session,
        tenant_id=uuid4(),
        permissions=frozenset({"product.view"}),
        target_locale="pt",
        include_latest_job=False,
    )

    assert result.total_skus == 11_863
    assert result.translated_skus == 0
    assert result.pending_skus == 11_863
    assert result.latest_job is None


def test_explicit_batch_action_resumes_hidden_batch_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    tenant_id = uuid4()
    candidate = SimpleNamespace(id=uuid4())
    context = SimpleNamespace(
        permissions=frozenset({"product.edit"}),
        tenant_id=tenant_id,
        organization_id=uuid4(),
        user_id=uuid4(),
        membership_id=uuid4(),
        is_platform_admin=True,
    )
    request = CatalogTranslationJobStartRequest(
        target_locale="es",
        mode="FULL_REBUILD",
        execution_mode="QWEN_BATCH",
        confirm_full_rebuild=True,
    )
    resumed: list[object] = []

    monkeypatch.setattr(
        catalog_translations,
        "resolved_qwen_batch_configuration",
        lambda _session: SimpleNamespace(
            identity=TranslationIdentity(provider="qwen", version="flash")
        ),
    )
    monkeypatch.setattr(
        catalog_translations,
        "language_package_storage_status",
        lambda: SimpleNamespace(configured=True),
    )
    monkeypatch.setattr(
        catalog_translations,
        "_expire_stale_job",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        catalog_translations,
        "_active_job",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        catalog_translations,
        "_latest_resumable_job_for_mode",
        lambda *_args, **_kwargs: candidate,
    )

    def resume(_session, *, context, job_id):
        resumed.extend([context, job_id])
        return "resumed"

    monkeypatch.setattr(catalog_translations, "resume_translation_job", resume)

    result = catalog_translations.start_translation_job(
        session,
        context=context,
        request=request,
    )

    assert result == "resumed"
    assert resumed == [context, candidate.id]


def test_safe_job_error_localizes_language_package_incomplete_message() -> None:
    message = catalog_translations._safe_job_error(
        TranslationProviderError(
            "language package translation left 1 fields incomplete"
        )
    )
    assert "仍有 1 个字段" in message


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


def test_translation_memory_force_refresh_bypasses_existing_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "需要重新翻译的规格"
    translated_batches: list[list[str]] = []
    translation_memory._reset_translation_memory_for_tests()
    monkeypatch.setattr(
        translation_memory,
        "_redis_get_many",
        lambda keys: {value: "Old translation" for value in keys},
    )
    monkeypatch.setattr(
        translation_memory,
        "_database_get_many",
        lambda **_kwargs: pytest.fail("forced text must bypass database memory"),
    )

    def translate_uncached(_translator, values, **_kwargs):
        batch = list(values)
        translated_batches.append(batch)
        return ({value: "Fresh translation" for value in batch}, {})

    monkeypatch.setattr(
        translation_memory,
        "_translate_uncached_values",
        translate_uncached,
    )
    monkeypatch.setattr(
        translation_memory,
        "_database_store_many",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        translation_memory,
        "_redis_store_many",
        lambda *_args, **_kwargs: None,
    )

    result = translation_memory.translate_values_with_memory(
        tenant_id=uuid4(),
        translator=_Translator(),
        values=[source],
        source_locale="zh-CN",
        target_locale="en-US",
        force_refresh_values={source},
    )

    assert result == {source: "Fresh translation"}
    assert translated_batches == [[source]]
    translation_memory._reset_translation_memory_for_tests()


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
        "resolved_catalog_translation_retry_count",
        lambda _session: 0,
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
        id=uuid4(),
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
    assert catalog_translations._job_realtime_translation_counts(job) == (2, 1)
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
    assert catalog_translations._job_realtime_translation_counts(job) == (2, 2)
    assert catalog_translations._job_finalization_counts(job) == (2, 2)
    assert job.current_sku_name is None


def test_realtime_text_batch_retries_and_preserves_upstream_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def translate_values(**kwargs):
        nonlocal calls
        calls += 1
        value = kwargs["values"][0]
        if calls < 3:
            kwargs["failure_sink"][value] = TranslationProviderError(
                "上游翻译服务返回 HTTP 429：RateLimitExceeded",
                category="UPSTREAM_HTTP",
                retryable=True,
                upstream_status_code=429,
            )
            return {}
        return {value: "Translated"}

    monkeypatch.setattr(
        catalog_translations,
        "translate_values_with_memory",
        translate_values,
    )
    monkeypatch.setattr(catalog_translations.time, "sleep", lambda _delay: None)

    outcome = catalog_translations._translate_realtime_text_outcome(
        _Translator(),
        tenant_id=uuid4(),
        values=["待翻译字段"],
        forced_values=set(),
        source_locale="zh-CN",
        target_locale="es",
        batch_items=1,
        batch_characters=100,
        max_retry_count=2,
    )

    assert calls == 3
    assert outcome.translations == {"待翻译字段": "Translated"}
    assert outcome.error is None
    assert [event.status for event in outcome.attempts] == [
        "FAILED",
        "FAILED",
        "SUCCEEDED",
    ]
    assert "HTTP 429" in (outcome.attempts[0].error_message or "")


def test_realtime_translation_skips_failed_batch_and_finishes_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = ["失败字段", "正常字段甲", "正常字段乙"]
    translated_memory: set[str] = set()
    attempted: list[str] = []

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
        "resolved_catalog_translation_retry_count",
        lambda _session: 0,
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

    def translate_outcome(_translator, **kwargs):
        value = kwargs["values"][0]
        attempted.append(value)
        now = catalog_translations.utcnow()
        if value == "失败字段":
            error = TranslationProviderError(
                "上游翻译服务返回 HTTP 503：ServiceUnavailable",
                category="UPSTREAM_HTTP",
                retryable=True,
                upstream_status_code=503,
            )
            return catalog_translations._TextTranslationOutcome(
                {},
                error,
                [
                    catalog_translations._BatchAttemptEvent(
                        attempt_no=1,
                        request_started_at=now,
                        first_byte_at=now,
                        completed_at=now,
                        status="FAILED",
                        processed_skus=0,
                        failed_skus=1,
                        error_message=str(error),
                    )
                ],
            )
        translated_memory.add(value)
        return catalog_translations._TextTranslationOutcome(
            {value: f"translated-{value}"},
            None,
            [
                catalog_translations._BatchAttemptEvent(
                    attempt_no=1,
                    request_started_at=now,
                    first_byte_at=now,
                    completed_at=now,
                    status="SUCCEEDED",
                    processed_skus=1,
                    failed_skus=0,
                )
            ],
        )

    monkeypatch.setattr(
        catalog_translations,
        "_batch_translation_availability",
        availability,
    )
    monkeypatch.setattr(
        catalog_translations,
        "_translate_realtime_text_outcome",
        translate_outcome,
    )
    monkeypatch.setattr(
        catalog_translations,
        "_pause_at_safe_checkpoint",
        lambda _session, _job: False,
    )

    job = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        target_locale="es",
        source_locale="zh-CN",
        total_skus=0,
        processed_skus=0,
        batch_request_payload={},
        current_sku_id=None,
        current_sku_name=None,
        updated_at=None,
    )

    with pytest.raises(TranslationProviderError) as error:
        catalog_translations._prepare_realtime_language_pack_values(
            _Session(),
            job=job,
            translator=_Translator(),
            rows=[],
            sku_translations={},
            previous_payload=None,
            reuse_previous=False,
        )

    assert attempted == values
    assert translated_memory == {"正常字段甲", "正常字段乙"}
    assert catalog_translations._job_realtime_translation_counts(job) == (3, 2)
    assert "已跳过 1 个失败批次" in str(error.value)
    assert "HTTP 503" in str(error.value)
