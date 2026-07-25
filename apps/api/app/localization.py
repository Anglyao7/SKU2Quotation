from __future__ import annotations

from typing import Literal, TypeAlias


UiLocale: TypeAlias = Literal["zh-CN", "en-US"]


def normalize_ui_locale(value: str | None) -> UiLocale:
    normalized = (value or "").strip().lower()
    return "en-US" if normalized.startswith("en") else "zh-CN"
