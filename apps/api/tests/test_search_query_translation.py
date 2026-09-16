from __future__ import annotations

import json

import httpx
import pytest

from app.services.search_query_translation import (
    BaiduSearchQueryTranslator,
    baidu_search_query_translation_is_configured,
)
from app.services.translation import TranslationProviderError


def test_baidu_search_query_translation_uses_llm_and_cache() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["appid"] == "app-id"
        assert payload["from"] == "en"
        assert payload["to"] == "zh"
        assert payload["model_type"] == "llm"
        return httpx.Response(
            200,
            json={
                "from": "en",
                "to": "zh",
                "trans_result": [{"src": payload["q"], "dst": "折叠宠物碗"}],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    translator = BaiduSearchQueryTranslator(
        api_key="api-key",
        app_id="app-id",
        client=client,
    )

    assert translator.translate(
        "foldable pet bowl",
        source_locale="en-US",
        target_locale="zh-CN",
    ) == "折叠宠物碗"
    assert translator.translate(
        "foldable pet bowl",
        source_locale="en-US",
        target_locale="zh-CN",
    ) == "折叠宠物碗"
    assert len(calls) == 1


def test_baidu_search_query_translation_rejects_missing_app_id() -> None:
    assert not baidu_search_query_translation_is_configured(
        {
            "BAIDU_SEARCH_TRANSLATION_API_KEY": "api-key",
            "BAIDU_SEARCH_TRANSLATION_APP_ID": "",
        }
    )


def test_baidu_search_query_translation_surfaces_upstream_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error_code": "58001", "error_msg": "language unsupported"},
        )

    translator = BaiduSearchQueryTranslator(
        api_key="api-key",
        app_id="app-id",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(TranslationProviderError, match="58001"):
        translator.translate(
            "text",
            source_locale="en-US",
            target_locale="zh-CN",
        )
