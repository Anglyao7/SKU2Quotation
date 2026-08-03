from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, TypeAlias


StorefrontLocale: TypeAlias = Literal[
    "zh-CN",
    "en-US",
    "es",
    "tr",
    "ar",
    "ja",
    "ko",
    "pt",
]

SUPPORTED_STOREFRONT_LOCALES: tuple[StorefrontLocale, ...] = (
    "zh-CN",
    "en-US",
    "es",
    "tr",
    "ar",
    "ja",
    "ko",
    "pt",
)
DEFAULT_STOREFRONT_LOCALES: tuple[StorefrontLocale, ...] = (
    "zh-CN",
    "en-US",
)

_LOCALE_ALIASES: dict[str, StorefrontLocale] = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "en": "en-US",
    "en-us": "en-US",
    "es": "es",
    "es-es": "es",
    "tr": "tr",
    "tr-tr": "tr",
    "ar": "ar",
    "ar-sa": "ar",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "pt": "pt",
    "pt-pt": "pt",
    "pt-br": "pt",
}


def normalize_storefront_locale(value: str | None) -> StorefrontLocale | None:
    if value is None:
        return None
    normalized = value.strip().replace("_", "-").casefold()
    if not normalized:
        return None
    return _LOCALE_ALIASES.get(normalized)


def effective_storefront_locales(
    values: Iterable[object] | None,
    *,
    source_locale: str,
) -> list[StorefrontLocale]:
    """Return one ordered, supported list that always contains the source language."""

    source = normalize_storefront_locale(source_locale) or "zh-CN"
    candidates = list(values) if values is not None else list(DEFAULT_STOREFRONT_LOCALES)
    normalized_values: list[StorefrontLocale] = []
    seen: set[str] = set()
    for value in [source, *candidates]:
        locale = normalize_storefront_locale(str(value))
        if locale is None or locale in seen:
            continue
        normalized_values.append(locale)
        seen.add(locale)
    return normalized_values or [source]
