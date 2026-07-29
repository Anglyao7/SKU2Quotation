from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlsplit

import httpx


SUPPORTED_LOCALE_CODES = {
    "zh": "ZH",
    "zh-CN": "ZH",
    "en": "EN",
    "en-US": "EN",
}


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


class DeepLXTranslator:
    """Small DeepLX adapter with a stable, provider-neutral contract."""

    identity = TranslationIdentity(provider="deeplx", version="v1")

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
        self._client = client or httpx.Client()

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


def catalog_translation_is_configured(
    values: Mapping[str, str] | None = None,
) -> bool:
    if values is None:
        values = os.environ
    profile = values.get("CATALOG_TRANSLATION_PROFILE", "disabled").strip().lower()
    return profile == "deeplx" and bool(
        values.get("DEEPLX_TRANSLATE_URL", "").strip()
    )


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
    if profile != "deeplx":
        raise TranslationProviderError(
            f"unsupported CATALOG_TRANSLATION_PROFILE: {profile}"
        )
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
    production = values.get("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    return _cached_deeplx_translator(
        endpoint,
        timeout_seconds,
        production,
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
