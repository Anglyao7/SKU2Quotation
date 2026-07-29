from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from app.services.catalog_translation import (
    CatalogTranslationSource,
    translate_catalog_sources,
    translate_catalog_values,
    translation_batches,
)
from app.services.translation import (
    DeepLXTranslator,
    TranslationIdentity,
    TranslationProviderError,
)


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
