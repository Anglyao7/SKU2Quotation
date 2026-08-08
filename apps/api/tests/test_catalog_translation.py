from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.services.catalog_translation import (
    CatalogTranslationSource,
    catalog_translation_value_is_complete,
    translate_catalog_sources,
    translate_catalog_values,
    translation_batches,
)
from app.services.translation import (
    AliyunAlimtTranslator,
    DeepLXTranslator,
    OpenAICompatibleTranslator,
    TranslationIdentity,
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)


class _FakeAliyunTranslationClient:
    def __init__(self) -> None:
        self.batch_requests: list[object] = []
        self.general_requests: list[object] = []

    def get_batch_translate_with_options(
        self,
        request: object,
        _runtime: object,
    ) -> object:
        self.batch_requests.append(request)
        source = json.loads(request.source_text)
        translated = [
            {
                "code": "200",
                "index": index,
                "translated": f"EN:{value}",
            }
            for index, value in reversed(list(source.items()))
        ]
        return SimpleNamespace(
            body=SimpleNamespace(
                code="200",
                message="success",
                translated_list=translated,
            )
        )

    def translate_general_with_options(
        self,
        request: object,
        _runtime: object,
    ) -> object:
        self.general_requests.append(request)
        return SimpleNamespace(
            body=SimpleNamespace(
                code="200",
                message="success",
                data=SimpleNamespace(translated=f"EN:{request.source_text}"),
            )
        )


def test_aliyun_adapter_uses_batch_api_and_preserves_catalog_markers() -> None:
    client = _FakeAliyunTranslationClient()
    translator = AliyunAlimtTranslator(
        access_key_id="test-access-key-id",
        access_key_secret="test-access-key-secret",
        client=client,
    )

    translated = translator.translate(
        "[[ATCV_000]]\n宠物包 [[ATCK_00000]]\n"
        "[[ATCV_001]]\n可折叠围栏 [[ATCK_00001]]",
        source_locale="zh-CN",
        target_locale="en-US",
    )

    assert translated == (
        "[[ATCV_000]]\nEN:宠物包 [[ATCK_00000]]\n"
        "[[ATCV_001]]\nEN:可折叠围栏 [[ATCK_00001]]"
    )
    assert len(client.batch_requests) == 1
    request = client.batch_requests[0]
    assert request.api_type == "translate_standard"
    assert request.scene == "general"
    assert request.source_language == "zh"
    assert request.target_language == "en"
    assert client.general_requests == []
    assert translator.identity.provider == "aliyun-alimt"


def test_aliyun_adapter_routes_large_fields_to_general_translation() -> None:
    client = _FakeAliyunTranslationClient()
    translator = AliyunAlimtTranslator(
        access_key_id="test-access-key-id",
        access_key_secret="test-access-key-secret",
        client=client,
    )
    source = "商品描述" * 300

    translated = translator.translate(
        f"[[ATCF_000_000]]\n{source}",
        source_locale="zh-CN",
        target_locale="es",
    )

    assert translated == f"[[ATCF_000_000]]\nEN:{source}"
    assert client.batch_requests == []
    assert len(client.general_requests) == 1


def test_deeplx_adapter_uses_json_contract_and_returns_safe_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/translate")
        assert request.headers["content-type"] == "application/json"
        payload = __import__("json").loads(request.content)
        assert payload == {
            "text": "智能宠物喂食器",
            "source_lang": "ZH",
            "target_lang": "EN",
        }
        return httpx.Response(
            200,
            json={"code": 200, "data": "Smart Pet Feeder"},
        )

    translator = DeepLXTranslator(
        endpoint="https://translation.example/secret-token/translate",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert translator.translate(
        "智能宠物喂食器",
        source_locale="zh-CN",
        target_locale="en-US",
    ) == "Smart Pet Feeder"


def test_deeplx_adapter_supports_automatic_source_language_detection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload == {
            "text": "¿Tienen este producto en azul?",
            "source_lang": "auto",
            "target_lang": "ZH",
        }
        return httpx.Response(
            200,
            json={"code": 200, "data": "这个商品有蓝色吗？"},
        )

    translator = DeepLXTranslator(
        endpoint="https://translation.example/secret-token/translate",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert translator.translate(
        "¿Tienen este producto en azul?",
        source_locale="auto",
        target_locale="zh-CN",
    ) == "这个商品有蓝色吗？"


@pytest.mark.parametrize(
    ("target_locale", "provider_code"),
    [
        ("es", "ES"),
        ("tr", "TR"),
        ("ar", "AR"),
        ("ja", "JA"),
        ("ko", "KO"),
        ("pt", "PT"),
    ],
)
def test_deeplx_adapter_supports_storefront_target_languages(
    target_locale: str,
    provider_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["source_lang"] == "ZH"
        assert payload["target_lang"] == provider_code
        return httpx.Response(200, json={"code": 200, "data": "translated"})

    translator = DeepLXTranslator(
        endpoint="https://translation.example/secret-token/translate",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert translator.translate(
        "商品",
        source_locale="zh-CN",
        target_locale=target_locale,
    ) == "translated"


def test_deeplx_adapter_never_exposes_secret_endpoint_on_failure() -> None:
    translator = DeepLXTranslator(
        endpoint="https://translation.example/do-not-leak/translate",
        production=True,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(503, text="upstream detail")
            )
        ),
    )

    with pytest.raises(TranslationProviderError) as error:
        translator.translate(
            "商品",
            source_locale="zh-CN",
            target_locale="en-US",
        )

    assert "503" in str(error.value)
    assert "do-not-leak" not in str(error.value)
    assert "upstream detail" not in str(error.value)


def test_openai_compatible_adapter_uses_chat_completions_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-test-key"
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "catalog-translation-model"
        assert payload["temperature"] == 0
        assert payload["max_tokens"] >= 2_500
        assert payload["reasoning_effort"] == "low"
        assert payload["messages"][1] == {
            "role": "user",
            "content": "智能宠物喂食器 SF-6L20",
        }
        system_prompt = payload["messages"][0]["content"]
        assert "Simplified Chinese" in system_prompt
        assert "English" in system_prompt
        assert "Return only the translation" in system_prompt
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "internal reasoning is ignored",
                            "content": "Smart pet feeder SF-6L20",
                        },
                    }
                ]
            },
        )

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example",
        api_key="private-test-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert translator.translate(
        "智能宠物喂食器 SF-6L20",
        source_locale="zh-CN",
        target_locale="en-US",
    ) == "Smart pet feeder SF-6L20"
    assert translator.identity.provider == "openai-compatible"
    assert "catalog-translation-model" in translator.identity.version


def test_openai_compatible_adapter_translates_marker_payload_as_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert __import__("json").loads(payload["messages"][1]["content"]) == [
            "宠物包 [[ATCK_00000]]",
            "可折叠围栏 [[ATCK_00001]]",
        ]
        assert "JSON array" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": __import__("json").dumps(
                                [
                                    "Pet bag [[ATCK_00000]]",
                                    "Foldable fence [[ATCK_00001]]",
                                ]
                            )
                        },
                    }
                ]
            },
        )

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example",
        api_key="private-test-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    translated = translator.translate(
        "[[ATCV_000]]\n宠物包 [[ATCK_00000]]\n"
        "[[ATCV_001]]\n可折叠围栏 [[ATCK_00001]]",
        source_locale="zh-CN",
        target_locale="en-US",
    )

    assert translated == (
        "[[ATCV_000]]\nPet bag [[ATCK_00000]]\n"
        "[[ATCV_001]]\nFoldable fence [[ATCK_00001]]"
    )


def test_openai_compatible_adapter_accepts_v1_base_and_strips_fence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "```text\nCercado dobrável PF-8G01\n```"
                        },
                    }
                ]
            },
        )

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/v1/",
        api_key="private-test-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert translator.translate(
        "可折叠围栏 PF-8G01",
        source_locale="zh-CN",
        target_locale="pt",
    ) == "Cercado dobrável PF-8G01"


def test_openai_compatible_adapter_marks_truncation_as_batch_recoverable() -> None:
    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example",
        api_key="private-test-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"content": ""},
                            }
                        ]
                    },
                )
            )
        ),
    )

    with pytest.raises(TranslationProviderError) as error:
        translator.translate(
            "[[ATCV_000]]\n商品\n[[ATCV_001]]\n产品",
            source_locale="zh-CN",
            target_locale="en-US",
        )

    assert error.value.recover_with_smaller_batches is True


def test_openai_compatible_adapter_marks_structured_timeout_as_recoverable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timeout", request=request)

    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example",
        api_key="private-test-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    )

    with pytest.raises(TranslationProviderError) as error:
        translator.translate(
            "[[ATCV_000]]\n商品\n[[ATCV_001]]\n产品",
            source_locale="zh-CN",
            target_locale="en-US",
        )

    assert error.value.recover_with_smaller_batches is True


def test_openai_compatible_adapter_marks_structured_http_400_as_recoverable() -> None:
    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example",
        api_key="private-test-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(400, json={"error": "denied"})
            )
        ),
    )

    with pytest.raises(TranslationProviderError) as error:
        translator.translate(
            "[[ATCV_000]]\n商品\n[[ATCV_001]]\n产品",
            source_locale="zh-CN",
            target_locale="pt",
        )

    assert error.value.recover_with_smaller_batches is True


def test_openai_compatible_adapter_never_exposes_credentials_on_failure() -> None:
    translator = OpenAICompatibleTranslator(
        base_url="https://translation.example/private-path",
        api_key="do-not-leak-key",
        model="catalog-translation-model",
        production=True,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    503,
                    text="sensitive upstream response",
                )
            )
        ),
    )

    with pytest.raises(TranslationProviderError) as error:
        translator.translate(
            "商品",
            source_locale="zh-CN",
            target_locale="en-US",
        )

    assert "503" in str(error.value)
    assert "private-path" not in str(error.value)
    assert "do-not-leak-key" not in str(error.value)
    assert "sensitive upstream response" not in str(error.value)


def test_openai_compatible_translation_profile_configuration() -> None:
    values = {
        "APP_ENV": "production",
        "CATALOG_TRANSLATION_PROFILE": "openai_compatible",
        "OPENAI_TRANSLATION_BASE_URL": "https://translation.example",
        "OPENAI_TRANSLATION_API_KEY": "private-test-key",
        "OPENAI_TRANSLATION_MODEL": "catalog-translation-model",
        "OPENAI_TRANSLATION_TIMEOUT_SECONDS": "15",
        "OPENAI_TRANSLATION_MAX_TOKENS": "8192",
    }

    assert catalog_translation_is_configured(values) is True
    translator = configured_catalog_translator(values)
    assert isinstance(translator, OpenAICompatibleTranslator)


def test_openai_compatible_translation_profile_requires_all_secrets() -> None:
    values = {
        "CATALOG_TRANSLATION_PROFILE": "openai_compatible",
        "OPENAI_TRANSLATION_BASE_URL": "https://translation.example",
        "OPENAI_TRANSLATION_API_KEY": "",
        "OPENAI_TRANSLATION_MODEL": "catalog-translation-model",
    }

    assert catalog_translation_is_configured(values) is False
    with pytest.raises(TranslationProviderError) as error:
        configured_catalog_translator(values)

    assert "OPENAI_TRANSLATION_API_KEY" in str(error.value)


def test_aliyun_translation_profile_configuration() -> None:
    values = {
        "CATALOG_TRANSLATION_PROFILE": "aliyun_alimt",
        "ALIYUN_TRANSLATION_ACCESS_KEY_ID": "test-access-key-id",
        "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET": "test-access-key-secret",
        "ALIYUN_TRANSLATION_REGION_ID": "cn-hangzhou",
        "ALIYUN_TRANSLATION_ENDPOINT": "mt.cn-hangzhou.aliyuncs.com",
    }

    assert catalog_translation_is_configured(values) is True
    translator = configured_catalog_translator(values)
    assert isinstance(translator, AliyunAlimtTranslator)
    assert translator.identity.provider == "aliyun-alimt"


def test_aliyun_translation_profile_requires_both_credentials() -> None:
    values = {
        "CATALOG_TRANSLATION_PROFILE": "aliyun_alimt",
        "ALIYUN_TRANSLATION_ACCESS_KEY_ID": "test-access-key-id",
        "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET": "",
    }

    assert catalog_translation_is_configured(values) is False
    with pytest.raises(TranslationProviderError) as error:
        configured_catalog_translator(values)

    assert "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET" in str(error.value)


class _ReplacingTranslator:
    identity = TranslationIdentity(provider="test", version="v1")

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        assert source_locale == "zh-CN"
        assert target_locale == "en-US"
        replacements = {
            "支持APP的智能宠物喂食器": "App-enabled smart pet feeder",
            "定时定量喂食": "Scheduled portion feeding",
            "宠物用品": "Pet supplies",
            "智能喂食": "Smart feeding",
        }
        translated = text
        for source, target in replacements.items():
            translated = translated.replace(source, target)
        return translated


def test_catalog_translation_preserves_model_codes_and_field_structure() -> None:
    source = CatalogTranslationSource(
        sku_id=uuid4(),
        sku_code="SF-6L20",
        name="支持APP的智能宠物喂食器 SF-6L20",
        description="定时定量喂食，容量 6L",
        category="宠物用品/智能喂食",
        tags=("智能喂食",),
        display_tag="智能喂食",
        product_version=3,
        sku_version=2,
        source_hash="a" * 64,
    )

    result = translate_catalog_sources(
        _ReplacingTranslator(),
        [source],
        source_locale="zh-CN",
        target_locale="en-US",
    )[0]

    assert result.name == "App-enabled smart pet feeder SF-6L20"
    assert result.source_hash == source.source_hash
    assert result.description == "Scheduled portion feeding，容量 6L"
    assert result.category == "Pet supplies/Smart feeding"
    assert result.tags == ("Smart feeding",)
    assert result.display_tag == "Smart feeding"


def test_translation_batches_bound_request_size_without_splitting_a_sku() -> None:
    sources = [
        CatalogTranslationSource(
            sku_id=uuid4(),
            sku_code=f"SKU-{index}",
            name="商品名称" * 5,
            description=None,
            category=None,
            tags=(),
            display_tag=None,
            product_version=1,
            sku_version=1,
            source_hash=str(index).zfill(64),
        )
        for index in range(5)
    ]

    batches = translation_batches(
        sources,
        max_items=2,
        max_characters=1_000,
    )

    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_catalog_value_translation_preserves_category_segments() -> None:
    translated = translate_catalog_values(
        _ReplacingTranslator(),
        ["宠物用品", "智能喂食"],
        source_locale="zh-CN",
        target_locale="en-US",
    )

    assert translated == ["Pet supplies", "Smart feeding"]


class _MangledMarkerTranslator:
    identity = TranslationIdentity(provider="test", version="mangled-markers")

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        assert "[[ATCK_00000]]" in text
        return (
            "[ATCV_000]]\nPrimeiro\n"
            "[[ATCV_001]]\nSegundo [ATCV_002]] [ATCV_002]]\n"
            "[[[ATCV_002]]]\nTerceiro [[[ATCK_00000]]]"
        )


def test_catalog_value_translation_tolerates_provider_mangled_markers() -> None:
    translated = translate_catalog_values(
        _MangledMarkerTranslator(),
        ["第一", "第二", "型号 AQ-320S"],
        source_locale="zh-CN",
        target_locale="pt",
    )

    assert translated == ["Primeiro", "Segundo", "Terceiro AQ-320S"]


class _UnchangedBatchTranslator:
    identity = TranslationIdentity(provider="test", version="unchanged-batch")

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        if text.startswith("[[ATCV_"):
            return text
        assert text == "MC Pet Pack"
        return "Pacote de animais MC"


def test_catalog_value_translation_retries_unchanged_prose_without_markers() -> None:
    translated = translate_catalog_values(
        _UnchangedBatchTranslator(),
        ["MC Pet Pack"],
        source_locale="en-US",
        target_locale="pt",
    )

    assert translated == ["Pacote de animais MC"]


class _PartiallyTranslatedBatchTranslator:
    identity = TranslationIdentity(provider="test", version="partial-batch")

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        if text.startswith("[[ATCV_"):
            return text
        return "Correia de corrente arco-íris"


def test_catalog_value_translation_retries_residual_chinese_without_markers() -> None:
    translated = translate_catalog_values(
        _PartiallyTranslatedBatchTranslator(),
        ["彩虹链拉带"],
        source_locale="zh-CN",
        target_locale="pt",
    )

    assert translated == ["Correia de corrente arco-íris"]


class _AlwaysPartialTranslator:
    identity = TranslationIdentity(provider="test", version="always-partial")

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        return text


def test_catalog_value_translation_rejects_residual_chinese() -> None:
    with pytest.raises(TranslationProviderError) as error:
        translate_catalog_values(
            _AlwaysPartialTranslator(),
            ["宠物用品"],
            source_locale="zh-CN",
            target_locale="pt",
        )

    assert error.value.recover_with_smaller_batches is True
    assert not catalog_translation_value_is_complete(
        "宠物用品",
        "Produtos para 宠物",
        source_locale="zh-CN",
        target_locale="pt",
    )
    assert catalog_translation_value_is_complete(
        "宠物用品",
        "ペット用品",
        source_locale="zh-CN",
        target_locale="ja",
    )
