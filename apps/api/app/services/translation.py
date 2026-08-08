from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
from alibabacloud_alimt20181012 import models as alimt_models
from alibabacloud_alimt20181012.client import Client as AlimtClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from Tea.exceptions import TeaException


SUPPORTED_LOCALE_CODES = {
    "auto": "auto",
    "zh": "ZH",
    "zh-CN": "ZH",
    "en": "EN",
    "en-US": "EN",
    "es": "ES",
    "es-ES": "ES",
    "tr": "TR",
    "tr-TR": "TR",
    "ar": "AR",
    "ar-SA": "AR",
    "ja": "JA",
    "ja-JP": "JA",
    "ko": "KO",
    "ko-KR": "KO",
    "pt": "PT",
    "pt-PT": "PT",
    "pt-BR": "PT",
}

ALIYUN_LOCALE_CODES = {
    "auto": "auto",
    "zh": "zh",
    "zh-CN": "zh",
    "en": "en",
    "en-US": "en",
    "es": "es",
    "es-ES": "es",
    "tr": "tr",
    "tr-TR": "tr",
    "ar": "ar",
    "ar-SA": "ar",
    "ja": "ja",
    "ja-JP": "ja",
    "ko": "ko",
    "ko-KR": "ko",
    "pt": "pt",
    "pt-PT": "pt",
    "pt-BR": "pt",
}

DEFAULT_ALIYUN_ALIMT_ENDPOINT = "mt.cn-hangzhou.aliyuncs.com"
DEFAULT_ALIYUN_ALIMT_REGION = "cn-hangzhou"

LOCALE_NAMES = {
    "auto": "automatically detected source language",
    "zh": "Simplified Chinese",
    "zh-CN": "Simplified Chinese",
    "en": "English",
    "en-US": "English",
    "es": "Spanish",
    "es-ES": "Spanish",
    "tr": "Turkish",
    "tr-TR": "Turkish",
    "ar": "Arabic",
    "ar-SA": "Arabic",
    "ja": "Japanese",
    "ja-JP": "Japanese",
    "ko": "Korean",
    "ko-KR": "Korean",
    "pt": "Portuguese",
    "pt-PT": "Portuguese",
    "pt-BR": "Brazilian Portuguese",
}

_CATALOG_BOUNDARY_PATTERN = re.compile(
    r"(?m)^[ \t]*(?P<marker>"
    r"\[\[ATCV_\d{3}\]\]|"
    r"\[\[ATCF_\d{3}_\d{3}\]\]"
    r")[ \t]*$"
)


@dataclass(frozen=True)
class TranslationIdentity:
    provider: str
    version: str


class TranslationProvider(Protocol):
    identity: TranslationIdentity

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str: ...


class TranslationProviderError(ValueError):
    """A user-safe provider failure that never includes endpoint credentials."""

    def __init__(
        self,
        message: str,
        *,
        recover_with_smaller_batches: bool = False,
    ) -> None:
        super().__init__(message)
        self.recover_with_smaller_batches = recover_with_smaller_batches


def _deeplx_endpoint(value: str, *, production: bool) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    allowed_schemes = {"https"} if production else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        raise TranslationProviderError(
            "DeepLX translation endpoint must be a valid HTTPS URL"
            if production
            else "DeepLX translation endpoint must be a valid HTTP(S) URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise TranslationProviderError(
            "DeepLX translation endpoint must not contain URL credentials"
        )
    if parsed.query or parsed.fragment:
        raise TranslationProviderError(
            "DeepLX translation endpoint must not contain a query or fragment"
        )
    if not parsed.path.rstrip("/").endswith("/translate"):
        raise TranslationProviderError(
            "DeepLX translation endpoint must end with /translate"
        )
    return normalized.rstrip("/")


def _provider_locale(locale: str) -> str:
    normalized = locale.strip()
    try:
        return SUPPORTED_LOCALE_CODES[normalized]
    except KeyError as exc:
        raise TranslationProviderError(
            f"unsupported catalog translation locale: {normalized or '(empty)'}"
        ) from exc


def _aliyun_locale(locale: str) -> str:
    normalized = locale.strip()
    try:
        return ALIYUN_LOCALE_CODES[normalized]
    except KeyError as exc:
        raise TranslationProviderError(
            f"unsupported Aliyun translation locale: {normalized or '(empty)'}"
        ) from exc


def _aliyun_endpoint(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return DEFAULT_ALIYUN_ALIMT_ENDPOINT
    parsed = urlsplit(
        normalized if "://" in normalized else f"https://{normalized}"
    )
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise TranslationProviderError(
            "Aliyun translation endpoint must be a valid HTTPS host"
        )
    return parsed.netloc


def _locale_name(locale: str) -> str:
    normalized = locale.strip()
    try:
        return LOCALE_NAMES[normalized]
    except KeyError as exc:
        raise TranslationProviderError(
            f"unsupported catalog translation locale: {normalized or '(empty)'}"
        ) from exc


def _openai_chat_completions_endpoint(
    value: str,
    *,
    production: bool,
) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized)
    allowed_schemes = {"https"} if production else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        raise TranslationProviderError(
            "OpenAI-compatible translation base URL must be a valid HTTPS URL"
            if production
            else (
                "OpenAI-compatible translation base URL must be a valid "
                "HTTP(S) URL"
            )
        )
    if parsed.username is not None or parsed.password is not None:
        raise TranslationProviderError(
            "OpenAI-compatible translation base URL must not contain credentials"
        )
    if parsed.query or parsed.fragment:
        raise TranslationProviderError(
            "OpenAI-compatible translation base URL must not contain a query "
            "or fragment"
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/chat/completions"):
        endpoint_path = path
    elif path.endswith("/v1"):
        endpoint_path = f"{path}/chat/completions"
    else:
        endpoint_path = f"{path}/v1/chat/completions"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, endpoint_path, "", "")
    )


def _strip_outer_markdown_fence(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith("```"):
        return normalized
    lines = normalized.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return normalized


def _catalog_marker_items(value: str) -> list[tuple[str, str]]:
    matches = list(_CATALOG_BOUNDARY_PATTERN.finditer(value))
    if not matches or value[: matches[0].start()].strip():
        return []
    items: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(
            value
        )
        content = value[match.end() : end].strip("\r\n")
        if not content.strip():
            return []
        items.append((match.group("marker"), content))
    return items


class DeepLXTranslator:
    """Small DeepLX adapter with a stable, provider-neutral contract."""

    translates_mixed_language_text = False
    # v4 invalidates older translation-memory rows that were allowed to keep
    # English fragments, untranslated CJK text, or unchanged marker-batch
    # output and stray provider-added marker brackets in storefront responses.
    identity = TranslationIdentity(provider="deeplx", version="v4")

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: float = 20.0,
        production: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise TranslationProviderError(
                "DEEPLX_TIMEOUT_SECONDS must be between 0 and 120"
            )
        self._endpoint = _deeplx_endpoint(endpoint, production=production)
        self._timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(trust_env=False)

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        if not text:
            return ""
        source = _provider_locale(source_locale)
        target = _provider_locale(target_locale)
        if source == target:
            return text
        try:
            response = self._client.post(
                self._endpoint,
                json={
                    "text": text,
                    "source_lang": source,
                    "target_lang": target,
                },
                headers={"Content-Type": "application/json"},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise TranslationProviderError(
                "translation provider request timed out"
            ) from exc
        except httpx.HTTPError as exc:
            raise TranslationProviderError(
                "translation provider request failed"
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise TranslationProviderError(
                f"translation provider returned HTTP {response.status_code}"
            )
        try:
            body = response.json()
            code = int(body.get("code", 200))
            translated = body["data"]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise TranslationProviderError(
                "translation provider returned an invalid response"
            ) from exc
        if code != 200 or not isinstance(translated, str):
            raise TranslationProviderError(
                "translation provider returned an invalid response"
            )
        normalized = translated.strip()
        if not normalized:
            raise TranslationProviderError(
                "translation provider returned an empty translation"
            )
        return normalized


def _split_translation_text(value: str, *, max_characters: int) -> list[str]:
    """Split a long field without cutting common sentence boundaries."""

    if len(value) <= max_characters:
        return [value]
    chunks: list[str] = []
    remaining = value
    preferred_boundaries = "\n。！？!?；;."
    while len(remaining) > max_characters:
        window = remaining[: max_characters + 1]
        split_at = max(
            (window.rfind(boundary) + 1 for boundary in preferred_boundaries),
            default=0,
        )
        if split_at < max_characters // 2:
            split_at = max(window.rfind(" ") + 1, window.rfind("\t") + 1)
        if split_at < max_characters // 2:
            split_at = max_characters
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return chunks


class AliyunAlimtTranslator:
    """Aliyun Machine Translation adapter using the General Edition API."""

    translates_mixed_language_text = False
    _API_VERSION = "2018-10-12"
    _BATCH_ITEM_LIMIT = 50
    _BATCH_ITEM_CHARACTERS = 1_000
    _BATCH_TOTAL_CHARACTERS = 8_000
    _GENERAL_CHARACTERS = 5_000

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        region_id: str = DEFAULT_ALIYUN_ALIMT_REGION,
        endpoint: str = DEFAULT_ALIYUN_ALIMT_ENDPOINT,
        timeout_seconds: float = 20.0,
        client: object | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise TranslationProviderError(
                "Aliyun translation timeout must be between 1 and 120 seconds"
            )
        normalized_access_key_id = access_key_id.strip()
        normalized_access_key_secret = access_key_secret.strip()
        normalized_region = region_id.strip() or DEFAULT_ALIYUN_ALIMT_REGION
        normalized_endpoint = _aliyun_endpoint(endpoint)
        if not normalized_access_key_id:
            raise TranslationProviderError("Aliyun AccessKey ID is required")
        if not normalized_access_key_secret:
            raise TranslationProviderError("Aliyun AccessKey Secret is required")

        self._timeout_seconds = timeout_seconds
        self._request_gate: Callable[[], None] | None = None
        self._runtime = util_models.RuntimeOptions(
            # Retries happen above the adapter so every real SDK request can
            # acquire its own platform-wide RPM slot.
            autoretry=False,
            max_attempts=1,
            read_timeout=round(timeout_seconds * 1_000),
            connect_timeout=min(round(timeout_seconds * 1_000), 10_000),
        )
        if client is None:
            config = open_api_models.Config(
                access_key_id=normalized_access_key_id,
                access_key_secret=normalized_access_key_secret,
                region_id=normalized_region,
                endpoint=normalized_endpoint,
                protocol="https",
                read_timeout=round(timeout_seconds * 1_000),
                connect_timeout=min(round(timeout_seconds * 1_000), 10_000),
            )
            client = AlimtClient(config)
        self._client = client
        fingerprint = hashlib.sha256(
            (
                f"{normalized_endpoint}\0{normalized_region}\0"
                f"{normalized_access_key_id[-4:]}\0{self._API_VERSION}"
            ).encode("utf-8")
        ).hexdigest()[:12]
        self.identity = TranslationIdentity(
            provider="aliyun-alimt",
            version=f"general:{self._API_VERSION}:{fingerprint}",
        )

    def install_request_gate(self, gate: Callable[[], None]) -> None:
        """Install a callback invoked immediately before every SDK request."""

        self._request_gate = gate

    def _acquire_request_slot(self) -> None:
        if self._request_gate is not None:
            self._request_gate()

    @staticmethod
    def _service_error(code: object, message: str | None = None) -> str:
        normalized = str(code or "unknown")
        friendly = {
            "101": "Aliyun translation request timed out",
            "105": "Aliyun does not support this language pair",
            "108": "Aliyun translation text exceeds the service limit",
            "109": "Aliyun RAM user is not authorized for machine translation",
            "110": "Aliyun Machine Translation is not activated",
            "113": "Aliyun Machine Translation is not activated or the account is in arrears",
        }.get(normalized)
        if friendly:
            return friendly
        safe_message = (message or "").strip()
        if safe_message and len(safe_message) <= 160:
            return f"Aliyun translation failed ({normalized}): {safe_message}"
        return f"Aliyun translation failed ({normalized})"

    @staticmethod
    def _request_succeeded(code: object) -> bool:
        return str(code).strip() == "200"

    def _translate_general(
        self,
        text: str,
        *,
        source: str,
        target: str,
    ) -> str:
        translated_chunks: list[str] = []
        for chunk in _split_translation_text(
            text,
            max_characters=self._GENERAL_CHARACTERS,
        ):
            request = alimt_models.TranslateGeneralRequest(
                format_type="text",
                scene="general",
                source_language=source,
                source_text=chunk,
                target_language=target,
            )
            try:
                self._acquire_request_slot()
                response = self._client.translate_general_with_options(
                    request,
                    self._runtime,
                )
            except TeaException as exc:
                raise TranslationProviderError(
                    self._service_error(getattr(exc, "code", None))
                ) from exc
            except Exception as exc:
                raise TranslationProviderError(
                    "Aliyun translation provider request failed"
                ) from exc
            body = getattr(response, "body", None)
            code = getattr(body, "code", None)
            if not self._request_succeeded(code):
                raise TranslationProviderError(
                    self._service_error(code, getattr(body, "message", None))
                )
            data = getattr(body, "data", None)
            translated = getattr(data, "translated", None)
            if not isinstance(translated, str) or not translated.strip():
                raise TranslationProviderError(
                    "Aliyun translation provider returned an empty translation"
                )
            translated_chunks.append(translated)
        return "".join(translated_chunks).strip()

    def _translate_batch_chunk(
        self,
        items: list[tuple[str, str]],
        *,
        source: str,
        target: str,
    ) -> dict[str, str]:
        payload = {str(index): text for index, (_marker, text) in enumerate(items)}
        request = alimt_models.GetBatchTranslateRequest(
            api_type="translate_standard",
            format_type="text",
            scene="general",
            source_language=source,
            source_text=json.dumps(payload, ensure_ascii=False),
            target_language=target,
        )
        try:
            self._acquire_request_slot()
            response = self._client.get_batch_translate_with_options(
                request,
                self._runtime,
            )
        except TeaException as exc:
            raise TranslationProviderError(
                self._service_error(getattr(exc, "code", None)),
                recover_with_smaller_batches=True,
            ) from exc
        except Exception as exc:
            raise TranslationProviderError(
                "Aliyun translation provider request failed",
                recover_with_smaller_batches=True,
            ) from exc
        body = getattr(response, "body", None)
        code = getattr(body, "code", None)
        if not self._request_succeeded(code):
            raise TranslationProviderError(
                self._service_error(code, getattr(body, "message", None)),
                recover_with_smaller_batches=True,
            )
        translated_list = getattr(body, "translated_list", None)
        if not isinstance(translated_list, list):
            raise TranslationProviderError(
                "Aliyun translation provider returned an invalid batch response",
                recover_with_smaller_batches=True,
            )
        translated: dict[str, str] = {}
        for row in translated_list:
            if not isinstance(row, Mapping):
                continue
            row_code = row.get("code", row.get("Code", 200))
            if not self._request_succeeded(row_code):
                raise TranslationProviderError(
                    self._service_error(row_code),
                    recover_with_smaller_batches=True,
                )
            index = row.get("index", row.get("Index"))
            value = row.get("translated", row.get("Translated"))
            if index is not None and isinstance(value, str) and value.strip():
                translated[str(index)] = value.strip()
        if len(translated) != len(items):
            raise TranslationProviderError(
                "Aliyun translation provider returned an incomplete batch response",
                recover_with_smaller_batches=True,
            )
        return translated

    def _translate_marker_items(
        self,
        items: list[tuple[str, str]],
        *,
        source: str,
        target: str,
    ) -> str:
        translated_by_marker: dict[str, str] = {}
        batch: list[tuple[str, str]] = []
        batch_characters = 0

        def flush() -> None:
            nonlocal batch, batch_characters
            if not batch:
                return
            translated = self._translate_batch_chunk(
                batch,
                source=source,
                target=target,
            )
            for index, (marker, _text) in enumerate(batch):
                translated_by_marker[marker] = translated[str(index)]
            batch = []
            batch_characters = 0

        for marker, value in items:
            if len(value) > self._BATCH_ITEM_CHARACTERS:
                flush()
                translated_by_marker[marker] = self._translate_general(
                    value,
                    source=source,
                    target=target,
                )
                continue
            if batch and (
                len(batch) >= self._BATCH_ITEM_LIMIT
                or batch_characters + len(value) > self._BATCH_TOTAL_CHARACTERS
            ):
                flush()
            batch.append((marker, value))
            batch_characters += len(value)
        flush()
        return "\n".join(
            f"{marker}\n{translated_by_marker[marker]}"
            for marker, _value in items
        )

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        if not text:
            return ""
        source = _aliyun_locale(source_locale)
        target = _aliyun_locale(target_locale)
        if source == target:
            return text
        marker_items = _catalog_marker_items(text)
        if marker_items:
            return self._translate_marker_items(
                marker_items,
                source=source,
                target=target,
            )
        return self._translate_general(text, source=source, target=target)


class OpenAICompatibleTranslator:
    """OpenAI chat-completions adapter for mixed-language catalog text."""

    translates_mixed_language_text = True
    _PROMPT_VERSION = "v2"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        max_tokens: int = 16_384,
        reasoning_effort: str | None = "low",
        production: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise TranslationProviderError(
                "OPENAI_TRANSLATION_TIMEOUT_SECONDS must be between 0 and 120"
            )
        if max_tokens < 512 or max_tokens > 32_768:
            raise TranslationProviderError(
                "OPENAI_TRANSLATION_MAX_TOKENS must be between 512 and 32768"
            )
        normalized_api_key = api_key.strip()
        if not normalized_api_key:
            raise TranslationProviderError(
                "OPENAI_TRANSLATION_API_KEY is required"
            )
        normalized_model = model.strip()
        if not normalized_model:
            raise TranslationProviderError(
                "OPENAI_TRANSLATION_MODEL is required"
            )
        normalized_reasoning_effort = (reasoning_effort or "").strip().lower()
        if normalized_reasoning_effort not in {
            "",
            "none",
            "minimal",
            "low",
            "medium",
            "high",
        }:
            raise TranslationProviderError(
                "OPENAI_TRANSLATION_REASONING_EFFORT must be empty, none, "
                "minimal, low, medium, or high"
            )
        self._endpoint = _openai_chat_completions_endpoint(
            base_url,
            production=production,
        )
        self._api_key = normalized_api_key
        self._model = normalized_model
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens
        self._reasoning_effort = normalized_reasoning_effort
        self._client = client or httpx.Client(trust_env=False)
        endpoint_host = urlsplit(self._endpoint).netloc.casefold()
        fingerprint = hashlib.sha256(
            (
                f"{endpoint_host}\0{normalized_model}\0"
                f"{self._PROMPT_VERSION}\0{normalized_reasoning_effort}"
            ).encode("utf-8")
        ).hexdigest()[:12]
        self.identity = TranslationIdentity(
            provider="openai-compatible",
            version=(
                f"{self._PROMPT_VERSION}:{normalized_model}:{fingerprint}"
            )[:120],
        )

    @staticmethod
    def _system_prompt(
        *,
        source_locale: str,
        target_locale: str,
        structured: bool,
    ) -> str:
        source_name = _locale_name(source_locale)
        target_name = _locale_name(target_locale)
        if structured:
            return (
                "Translate every natural-language part in the JSON array "
                f"from {source_name} into {target_name}; the input may mix "
                "languages. If adjacent Chinese and English phrases repeat "
                "the same meaning, output that meaning once, including when "
                "the duplicate is inside parentheses. Preserve [[ATCK_...]] "
                "placeholders, SKU codes, model numbers, units, dimensions, "
                "punctuation, and line breaks. Do not leave prose in another "
                "language untranslated; ITEM NO, SIZE, COLOR, and DESCRIPTION "
                "are translatable labels, not model codes. Translate or "
                "transliterate names and brands written in the source script. "
                "When the target is not Chinese or Japanese, no Chinese prose "
                "may remain. Return only a JSON "
                "array with the same length and order. No analysis or Markdown."
            )
        return (
            f"Translate this commerce text from {source_name} into "
            f"{target_name}; it may mix languages. If adjacent Chinese and "
            "English phrases repeat the same meaning, output that meaning "
            "once, including when the duplicate is inside parentheses. "
            "Preserve SKU codes, model numbers, units, dimensions, "
            "punctuation, line breaks, and [[ATCK_...]] placeholders. Do not "
            "leave prose in another language untranslated; ITEM NO, SIZE, "
            "COLOR, and DESCRIPTION are translatable labels, not model codes. "
            "Translate or transliterate names and brands written in the source "
            "script. When the target is not Chinese or Japanese, no Chinese "
            "prose may remain. "
            "Return only the translation, with no analysis or Markdown."
        )

    def translate(
        self,
        text: str,
        *,
        source_locale: str,
        target_locale: str,
    ) -> str:
        if not text:
            return ""
        source = _provider_locale(source_locale)
        target = _provider_locale(target_locale)
        if source == target:
            return text
        marker_items = _catalog_marker_items(text)
        structured = bool(marker_items)
        request_text = (
            json.dumps(
                [content for _marker, content in marker_items],
                ensure_ascii=False,
            )
            if structured
            else text
        )
        output_budget = min(
            self._max_tokens,
            max(2_500, 1_500 + len(request_text) * 2),
        )
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(
                        source_locale=source_locale,
                        target_locale=target_locale,
                        structured=structured,
                    ),
                },
                {"role": "user", "content": request_text},
            ],
            "temperature": 0,
            "max_tokens": output_budget,
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
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
                "translation provider request timed out",
                recover_with_smaller_batches=structured,
            ) from exc
        except httpx.HTTPError as exc:
            raise TranslationProviderError(
                "translation provider request failed",
                recover_with_smaller_batches=structured,
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise TranslationProviderError(
                f"translation provider returned HTTP {response.status_code}",
                recover_with_smaller_batches=(
                    structured
                    and response.status_code in {400, 408, 500, 502, 503, 504}
                ),
            )
        try:
            body = response.json()
            choices = body["choices"]
            choice = choices[0]
            finish_reason = str(choice.get("finish_reason") or "").strip()
            message = choice["message"]
            content = message["content"]
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise TranslationProviderError(
                "translation provider returned an invalid response"
            ) from exc
        if finish_reason == "length":
            raise TranslationProviderError(
                "translation provider response was truncated",
                recover_with_smaller_batches=structured,
            )
        if isinstance(content, list):
            content = "".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, Mapping)
            )
        if not isinstance(content, str):
            raise TranslationProviderError(
                "translation provider returned an invalid response"
            )
        normalized = _strip_outer_markdown_fence(content)
        if not normalized:
            raise TranslationProviderError(
                "translation provider returned an empty translation",
                recover_with_smaller_batches=structured,
            )
        if structured:
            try:
                translated_items = json.loads(normalized)
            except json.JSONDecodeError as exc:
                raise TranslationProviderError(
                    "translation provider returned invalid structured content",
                    recover_with_smaller_batches=True,
                ) from exc
            if (
                not isinstance(translated_items, list)
                or len(translated_items) != len(marker_items)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in translated_items
                )
            ):
                raise TranslationProviderError(
                    "translation provider returned invalid structured content",
                    recover_with_smaller_batches=True,
                )
            return "\n".join(
                f"{marker}\n{translated.strip()}"
                for (marker, _source), translated in zip(
                    marker_items,
                    translated_items,
                    strict=True,
                )
            )
        return normalized


def catalog_translation_is_configured(
    values: Mapping[str, str] | None = None,
) -> bool:
    if values is None:
        values = os.environ
    profile = values.get("CATALOG_TRANSLATION_PROFILE", "disabled").strip().lower()
    if profile == "deeplx":
        return bool(values.get("DEEPLX_TRANSLATE_URL", "").strip())
    if profile == "openai_compatible":
        return all(
            bool(values.get(name, "").strip())
            for name in (
                "OPENAI_TRANSLATION_BASE_URL",
                "OPENAI_TRANSLATION_API_KEY",
                "OPENAI_TRANSLATION_MODEL",
            )
        )
    if profile == "aliyun_alimt":
        return all(
            bool(values.get(name, "").strip())
            for name in (
                "ALIYUN_TRANSLATION_ACCESS_KEY_ID",
                "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET",
            )
        )
    return False


def configured_catalog_translator(
    values: Mapping[str, str] | None = None,
) -> TranslationProvider:
    if values is None:
        values = os.environ
    profile = values.get("CATALOG_TRANSLATION_PROFILE", "disabled").strip().lower()
    if profile in {"", "disabled", "none"}:
        raise TranslationProviderError(
            "catalog translation provider is not configured"
        )
    if profile not in {"deeplx", "openai_compatible", "aliyun_alimt"}:
        raise TranslationProviderError(
            f"unsupported CATALOG_TRANSLATION_PROFILE: {profile}"
        )
    production = values.get("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    if profile == "deeplx":
        endpoint = values.get("DEEPLX_TRANSLATE_URL", "").strip()
        if not endpoint:
            raise TranslationProviderError("DEEPLX_TRANSLATE_URL is required")
        try:
            timeout_seconds = float(
                values.get("DEEPLX_TIMEOUT_SECONDS", "20").strip()
            )
        except ValueError as exc:
            raise TranslationProviderError(
                "DEEPLX_TIMEOUT_SECONDS must be a number"
            ) from exc
        return _cached_deeplx_translator(
            endpoint,
            timeout_seconds,
            production,
        )

    if profile == "aliyun_alimt":
        access_key_id = values.get(
            "ALIYUN_TRANSLATION_ACCESS_KEY_ID",
            "",
        ).strip()
        access_key_secret = values.get(
            "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET",
            "",
        ).strip()
        if not access_key_id:
            raise TranslationProviderError(
                "ALIYUN_TRANSLATION_ACCESS_KEY_ID is required"
            )
        if not access_key_secret:
            raise TranslationProviderError(
                "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET is required"
            )
        try:
            timeout_seconds = float(
                values.get("ALIYUN_TRANSLATION_TIMEOUT_SECONDS", "20").strip()
            )
        except ValueError as exc:
            raise TranslationProviderError(
                "ALIYUN_TRANSLATION_TIMEOUT_SECONDS must be a number"
            ) from exc
        return aliyun_alimt_translation_provider(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region_id=values.get(
                "ALIYUN_TRANSLATION_REGION_ID",
                DEFAULT_ALIYUN_ALIMT_REGION,
            ).strip(),
            endpoint=values.get(
                "ALIYUN_TRANSLATION_ENDPOINT",
                DEFAULT_ALIYUN_ALIMT_ENDPOINT,
            ).strip(),
            timeout_seconds=timeout_seconds,
        )

    base_url = values.get("OPENAI_TRANSLATION_BASE_URL", "").strip()
    api_key = values.get("OPENAI_TRANSLATION_API_KEY", "").strip()
    model = values.get("OPENAI_TRANSLATION_MODEL", "").strip()
    if not base_url:
        raise TranslationProviderError(
            "OPENAI_TRANSLATION_BASE_URL is required"
        )
    if not api_key:
        raise TranslationProviderError("OPENAI_TRANSLATION_API_KEY is required")
    if not model:
        raise TranslationProviderError("OPENAI_TRANSLATION_MODEL is required")
    try:
        timeout_seconds = float(
            values.get("OPENAI_TRANSLATION_TIMEOUT_SECONDS", "20").strip()
        )
    except ValueError as exc:
        raise TranslationProviderError(
            "OPENAI_TRANSLATION_TIMEOUT_SECONDS must be a number"
        ) from exc
    try:
        max_tokens = int(
            values.get("OPENAI_TRANSLATION_MAX_TOKENS", "16384").strip()
        )
    except ValueError as exc:
        raise TranslationProviderError(
            "OPENAI_TRANSLATION_MAX_TOKENS must be an integer"
        ) from exc
    reasoning_effort = values.get(
        "OPENAI_TRANSLATION_REASONING_EFFORT",
        "low",
    ).strip()
    return openai_compatible_translation_provider(
        base_url,
        api_key,
        model,
        timeout_seconds,
        max_tokens,
        reasoning_effort,
        production,
    )


def openai_compatible_translation_provider(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 20.0,
    max_tokens: int = 16_384,
    reasoning_effort: str = "low",
    production: bool = False,
) -> TranslationProvider:
    """Build a cached provider from explicit, already-resolved settings."""

    return _cached_openai_compatible_translator(
        base_url.strip().rstrip("/"),
        api_key.strip(),
        model.strip(),
        timeout_seconds,
        max_tokens,
        reasoning_effort.strip().lower(),
        production,
    )


def aliyun_alimt_translation_provider(
    *,
    access_key_id: str,
    access_key_secret: str,
    region_id: str = DEFAULT_ALIYUN_ALIMT_REGION,
    endpoint: str = DEFAULT_ALIYUN_ALIMT_ENDPOINT,
    timeout_seconds: float = 20.0,
) -> TranslationProvider:
    """Build a cached Aliyun General Edition translation provider."""

    return _cached_aliyun_alimt_translator(
        access_key_id.strip(),
        access_key_secret.strip(),
        region_id.strip() or DEFAULT_ALIYUN_ALIMT_REGION,
        _aliyun_endpoint(endpoint),
        timeout_seconds,
    )


@lru_cache(maxsize=4)
def _cached_deeplx_translator(
    endpoint: str,
    timeout_seconds: float,
    production: bool,
) -> DeepLXTranslator:
    return DeepLXTranslator(
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        production=production,
    )


@lru_cache(maxsize=4)
def _cached_aliyun_alimt_translator(
    access_key_id: str,
    access_key_secret: str,
    region_id: str,
    endpoint: str,
    timeout_seconds: float,
) -> AliyunAlimtTranslator:
    return AliyunAlimtTranslator(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id=region_id,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
    )


@lru_cache(maxsize=4)
def _cached_openai_compatible_translator(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
    max_tokens: int,
    reasoning_effort: str,
    production: bool,
) -> OpenAICompatibleTranslator:
    return OpenAICompatibleTranslator(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        production=production,
    )
