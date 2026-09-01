from __future__ import annotations

from typing import TypeAlias

from .storefront_locales import StorefrontLocale, normalize_storefront_locale


# The console and storefront intentionally share one locale vocabulary.  UI
# copy is static, while catalog facts are read from the published language
# package for the same locale.
UiLocale: TypeAlias = StorefrontLocale


def normalize_ui_locale(value: str | None) -> UiLocale:
    return normalize_storefront_locale(value) or "zh-CN"
