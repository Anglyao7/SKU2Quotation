"""Privacy helpers for values that cross the public storefront boundary.

SKU option values are intentionally kept as a flexible JSON object because the
import template can grow over time.  That flexibility also means fields that
are useful to an operator (for example, the internal SKU note) must be removed
at every public serialization boundary instead of relying on the frontend to
hide them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_PRIVATE_SKU_OPTION_KEYS = frozenset(
    {
        "备注",
        "備註",
        "note",
        "notes",
        "remark",
        "remarks",
    }
)
_OPTION_KEY_SEPARATOR_PATTERN = re.compile(r"[\s\-_/:：,.，。()（）\[\]【】]+")
_SPECIFICATION_PART_PATTERN = re.compile(r"(?:\r?\n|[;；])+")
_SPECIFICATION_LABEL_PATTERN = re.compile(r"^\s*([^:：]{1,80})\s*[:：]")


def _normalized_option_key(value: object) -> str:
    return _OPTION_KEY_SEPARATOR_PATTERN.sub("", str(value or "").casefold().strip())


_NORMALIZED_PRIVATE_SKU_OPTION_KEYS = frozenset(
    _normalized_option_key(value) for value in _PRIVATE_SKU_OPTION_KEYS
)


def is_private_sku_option_key(value: object) -> bool:
    """Return whether an option label is reserved for merchant-side notes."""

    return _normalized_option_key(value) in _NORMALIZED_PRIVATE_SKU_OPTION_KEYS


def _public_option_mapping(values: Mapping[object, Any]) -> dict[str, Any]:
    """Copy an option mapping while removing private labels.

    The internal quote marker can contain a source option mapping for
    localization and document rendering.  It is retained for compatibility,
    but its nested source mapping is sanitized as well so older quote drafts
    cannot leak a note through that fallback path.
    """

    public: dict[str, Any] = {}
    for raw_key, value in values.items():
        key = str(raw_key).strip()
        if not key or is_private_sku_option_key(key):
            continue
        if key == "_sku2quotation" and isinstance(value, Mapping):
            marker = dict(value)
            marker_keys = marker.get("variant_option_keys")
            if isinstance(marker_keys, list):
                marker["variant_option_keys"] = [
                    str(marker_key).strip()
                    for marker_key in marker_keys
                    if str(marker_key).strip()
                    and not is_private_sku_option_key(marker_key)
                ]
            source_values = marker.get("quote_source_option_values")
            if isinstance(source_values, Mapping):
                marker["quote_source_option_values"] = _public_option_mapping(
                    source_values
                )
            public[key] = marker
            continue
        public[key] = value
    return public


def public_sku_option_values(values: object) -> dict[str, Any]:
    """Return the SKU option values safe for a public API response."""

    if not isinstance(values, Mapping):
        return {}
    return _public_option_mapping(values)


def public_specification(value: object) -> str | None:
    """Remove private ``备注: ...`` segments from saved quote specifications.

    New quotes no longer generate these segments, while this guard also makes
    previously saved quote drafts safe when they are viewed or downloaded.
    """

    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None

    public_parts: list[str] = []
    for part in _SPECIFICATION_PART_PATTERN.split(text):
        normalized_part = part.strip()
        if not normalized_part:
            continue
        label_match = _SPECIFICATION_LABEL_PATTERN.match(normalized_part)
        if label_match and is_private_sku_option_key(label_match.group(1)):
            continue
        public_parts.append(normalized_part)
    return "；".join(public_parts) or None
