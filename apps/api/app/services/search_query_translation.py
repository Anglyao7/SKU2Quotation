"""Translate public storefront search phrases into the catalog source language.

This adapter is intentionally separate from catalog language-pack translation.
It is only used to normalize a visitor's short search phrase before catalog
retrieval.  The API key remains server-side and failures are fail-open: the
caller can continue searching with the original phrase. Runtime settings are
managed by the configuration center, while the environment adapter remains as
a compatibility fallback for existing deployments.
"""

from __future__ import annotations

import logging
import os
import re
from collections import OrderedDict
from functools import lru_cache
from threading import RLock
from time import monotonic
from typing import Any, Mapping

import httpx

from .translation import TranslationProviderError, _safe_upstream_text


logger = logging.getLogger(__name__)

DEFAULT_BAIDU_SEARCH_TRANSLATION_ENDPOINT = (
    "https://fanyi-api.baidu.com/ait/api/aiTextTranslate"
)
DEFAULT_BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS = 8.0
DEFAULT_BAIDU_SEARCH_TRANSLATION_CACHE_TTL_SECONDS = 86_400
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")

# Baidu's translation API uses its own language-code table.  Keep this map
# separate from the storefront's ISO-like locale names.
BAIDU_LOCALE_CODES = {
    "zh": "zh",
    "zh-cn": "zh",
    "en": "en",
    "en-us": "en",
    "es": "spa",
    "es-es": "spa",
    "tr": "tr",
    "tr-tr": "tr",
    "ar": "ara",
    "ar-sa": "ara",
    "ja": "jp",
    "ja-jp": "jp",
    "ko": "kor",
    "ko-kr": "kor",
    "pt": "pt",
    "pt-pt": "pt",
    "pt-br": "pot",
    "fr": "fra",
    "fr-fr": "fra",
    "fa": "per",
    "fa-ir": "per",
    "ru": "ru",
    "ru-ru": "ru",
}


def _normalized_locale(value: str) -> str:
    return value.strip().casefold().replace("_", "-")


def _baidu_locale(value: str) -> str:
    normalized = _normalized_locale(value)
    try:
        return BAIDU_LOCALE_CODES[normalized]
    except KeyError as exc:
        raise TranslationProviderError(
            f"Baidu search translation does not support locale {value!r}",
            category="CONFIGURATION",
            retryable=False,
        ) from exc


def _timeout_seconds(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise TranslationProviderError(
            "BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS must be a number",
            category="CONFIGURATION",
            retryable=False,
        ) from exc
    if timeout <= 0 or timeout > 120:
        raise TranslationProviderError(
            "BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS must be between 1 and 120 seconds",
            category="CONFIGURATION",
            retryable=False,
        )
    return timeout


def _cache_ttl_seconds(value: str) -> int:
    try:
        ttl = int(value)
    except ValueError:
        ttl = DEFAULT_BAIDU_SEARCH_TRANSLATION_CACHE_TTL_SECONDS
    return max(60, min(ttl, 2_592_000))


def _safe_error(body: object) -> str | None:
    if not isinstance(body, Mapping):
        return None
    code = _safe_upstream_text(body.get("error_code"))
    message = _safe_upstream_text(body.get("error_msg"))
    if code and message:
        return f"{code}: {message}"
    return message or code


class BaiduSearchQueryTranslator:
    """Baidu AI text translation adapter for short storefront queries."""

    def __init__(
        self,
        *,
        api_key: str,
        app_id: str,
        endpoint: str = DEFAULT_BAIDU_SEARCH_TRANSLATION_ENDPOINT,
        timeout_seconds: float = DEFAULT_BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS,
        cache_ttl_seconds: int = DEFAULT_BAIDU_SEARCH_TRANSLATION_CACHE_TTL_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        normalized_app_id = app_id.strip()
        normalized_endpoint = endpoint.strip().rstrip("/")
        if not normalized_key:
            raise TranslationProviderError(
                "BAIDU_SEARCH_TRANSLATION_API_KEY is required",
                category="CONFIGURATION",
                retryable=False,
            )
        if not normalized_app_id:
            raise TranslationProviderError(
                "BAIDU_SEARCH_TRANSLATION_APP_ID is required",
                category="CONFIGURATION",
                retryable=False,
            )
        if not normalized_endpoint.startswith("https://"):
            raise TranslationProviderError(
                "BAIDU_SEARCH_TRANSLATION_ENDPOINT must be an HTTPS URL",
                category="CONFIGURATION",
                retryable=False,
            )
        self._api_key = normalized_key
        self._app_id = normalized_app_id
        self._endpoint = normalized_endpoint
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = max(60, cache_ttl_seconds)
        self._client = client or httpx.Client(trust_env=False)
        self._cache: OrderedDict[tuple[str, str, str], tuple[float, str]] = (
            OrderedDict()
        )
        self._cache_lock = RLock()
        self.identity = "baidu-ai-search-query:v1"

    def _cache_get(self, key: tuple[str, str, str]) -> str | None:
        now = monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            created_at, value = entry
            if now - created_at > self._cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return value

    def _cache_put(self, key: tuple[str, str, str], value: str) -> None:
        with self._cache_lock:
            self._cache[key] = (monotonic(), value)
            self._cache.move_to_end(key)
            while len(self._cache) > 2_048:
                self._cache.popitem(last=False)

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        source = _baidu_locale(source_locale)
        target = _baidu_locale(target_locale)
        normalized = " ".join(text.split()).strip()
        if not normalized or source == target:
            return normalized
        cache_key = (normalized, source, target)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload: dict[str, object] = {
            "appid": self._app_id,
            "from": source,
            "to": target,
            "q": normalized,
            "model_type": "llm",
            "reference": (
                "这是商品搜索词，只翻译自然语言。保留 SKU、货号、型号、数字、"
                "单位、尺寸和斜杠 /；斜杠是普通分隔符，不是命令或工具调用。"
                "只返回译文，不要解释。"
            ),
        }
        try:
            response = self._client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise TranslationProviderError(
                "百度搜索词翻译请求超时",
                category="UPSTREAM_TIMEOUT",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise TranslationProviderError(
                "无法连接百度搜索词翻译服务",
                category="UPSTREAM_NETWORK",
                retryable=True,
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            try:
                error_body = response.json() if response.content else None
            except (TypeError, ValueError):
                error_body = None
            detail = _safe_error(error_body)
            suffix = f"：{detail}" if detail else ""
            raise TranslationProviderError(
                f"百度搜索词翻译返回 HTTP {response.status_code}{suffix}",
                category="UPSTREAM_HTTP",
                retryable=response.status_code in {408, 425, 429, 500, 502, 503, 504},
                upstream_status_code=response.status_code,
            )
        try:
            body: Any = response.json()
        except (TypeError, ValueError) as exc:
            raise TranslationProviderError(
                "百度搜索词翻译返回的响应不是有效 JSON",
                category="UPSTREAM_RESPONSE",
                retryable=True,
            ) from exc
        if not isinstance(body, Mapping):
            raise TranslationProviderError(
                "百度搜索词翻译返回的数据格式无效",
                category="UPSTREAM_RESPONSE",
                retryable=True,
            )
        error_detail = _safe_error(body)
        if error_detail:
            raise TranslationProviderError(
                f"百度搜索词翻译失败：{error_detail}",
                category="UPSTREAM_RESPONSE",
                retryable=False,
            )
        translated_items = body.get("trans_result")
        if not isinstance(translated_items, list):
            raise TranslationProviderError(
                "百度搜索词翻译返回中缺少 trans_result",
                category="UPSTREAM_RESPONSE",
                retryable=True,
            )
        translated = " ".join(
            str(item.get("dst", "")).strip()
            for item in translated_items
            if isinstance(item, Mapping) and str(item.get("dst", "")).strip()
        ).strip()
        if not translated:
            raise TranslationProviderError(
                "百度搜索词翻译返回了空译文",
                category="UPSTREAM_RESPONSE",
                retryable=True,
            )
        self._cache_put(cache_key, translated)
        return translated


def baidu_search_query_translation_is_configured(
    values: Mapping[str, str] | None = None,
) -> bool:
    values = values or os.environ
    return bool(
        values.get("BAIDU_SEARCH_TRANSLATION_API_KEY", "").strip()
        and values.get("BAIDU_SEARCH_TRANSLATION_APP_ID", "").strip()
    )


@lru_cache(maxsize=2)
def _cached_baidu_search_query_translator(
    api_key: str,
    app_id: str,
    endpoint: str,
    timeout_seconds: float,
    cache_ttl_seconds: int,
) -> BaiduSearchQueryTranslator:
    return BaiduSearchQueryTranslator(
        api_key=api_key,
        app_id=app_id,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        cache_ttl_seconds=cache_ttl_seconds,
    )


def configured_baidu_search_query_translator(
    values: Mapping[str, str] | None = None,
) -> BaiduSearchQueryTranslator:
    values = values or os.environ
    if not baidu_search_query_translation_is_configured(values):
        raise TranslationProviderError(
            "百度搜索词翻译未配置 API Key 或 AppID",
            category="CONFIGURATION",
            retryable=False,
        )
    endpoint = values.get(
        "BAIDU_SEARCH_TRANSLATION_ENDPOINT",
        DEFAULT_BAIDU_SEARCH_TRANSLATION_ENDPOINT,
    ).strip()
    timeout_seconds = _timeout_seconds(
        values.get(
            "BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS",
            str(DEFAULT_BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS),
        )
    )
    cache_ttl_seconds = _cache_ttl_seconds(
        values.get(
            "BAIDU_SEARCH_TRANSLATION_CACHE_TTL_SECONDS",
            str(DEFAULT_BAIDU_SEARCH_TRANSLATION_CACHE_TTL_SECONDS),
        )
    )
    return _cached_baidu_search_query_translator(
        values["BAIDU_SEARCH_TRANSLATION_API_KEY"].strip(),
        values["BAIDU_SEARCH_TRANSLATION_APP_ID"].strip(),
        endpoint,
        timeout_seconds,
        cache_ttl_seconds,
    )


def cached_baidu_search_query_translator(
    *,
    api_key: str,
    app_id: str,
    endpoint: str = DEFAULT_BAIDU_SEARCH_TRANSLATION_ENDPOINT,
    timeout_seconds: float = DEFAULT_BAIDU_SEARCH_TRANSLATION_TIMEOUT_SECONDS,
    cache_ttl_seconds: int = DEFAULT_BAIDU_SEARCH_TRANSLATION_CACHE_TTL_SECONDS,
) -> BaiduSearchQueryTranslator:
    """Reuse one HTTP client per managed configuration instead of per request."""

    return _cached_baidu_search_query_translator(
        api_key.strip(),
        app_id.strip(),
        endpoint.strip().rstrip("/"),
        float(timeout_seconds),
        int(cache_ttl_seconds),
    )
