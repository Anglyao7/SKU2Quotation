"""Conservative matching rules for reusable catalog translations.

Only presentation-only whitespace and numeric values are generalized.  A word
change (including a color, material, negation, or product type) must still go
to the translation provider; edit distance alone is not a safe translation.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata


_HORIZONTAL_SPACE = re.compile(r"[\t\u00a0\u3000 ]+")
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)*(?!\d)")
_ASCII_SUFFIX = re.compile(r"[A-Za-z]+")
_PRODUCT_CODE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]+(?:[-_]?[A-Za-z0-9]+)*[-_]?\d+[A-Za-z0-9_-]*"
)
_TRANSLATABLE_CONTEXT = re.compile(r"[A-Za-z\u3400-\u9fff]")
_NUMERIC_UNITS = frozenset(
    {
        "a", "cm", "g", "gb", "kg", "km", "l", "m", "mah", "mb", "mg",
        "ml", "mm", "oz", "pc", "pcs", "v", "w",
    }
)
_MAX_TEMPLATE_NUMBERS = 8


def normalized_translation_text(value: str) -> str:
    """Preserve punctuation, case, and line boundaries while ignoring spacing."""

    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    return "\n".join(
        _HORIZONTAL_SPACE.sub(" ", line).strip()
        for line in normalized.strip().split("\n")
    )


def normalized_translation_hash(value: str) -> str:
    return hashlib.sha256(normalized_translation_text(value).encode("utf-8")).hexdigest()


def _numeric_parts(value: str) -> tuple[str, tuple[str, ...]] | None:
    source = normalized_translation_text(value)
    # Do not produce a template for a title containing a model/SKU-like code.
    # Numeric substitutions inside identifiers are not semantically safe.
    if _PRODUCT_CODE.search(source):
        return None
    matches = list(_NUMBER.finditer(source))
    if not 1 <= len(matches) <= _MAX_TEMPLATE_NUMBERS:
        return None
    if len(_TRANSLATABLE_CONTEXT.findall(source)) < 2:
        return None
    numbers = tuple(match.group() for match in matches)
    for match in matches:
        suffix = _ASCII_SUFFIX.match(source, match.end())
        if suffix and suffix.group().casefold() not in _NUMERIC_UNITS:
            return None
    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.extend((source[cursor : match.start()], "\x01"))
        cursor = match.end()
    pieces.append(source[cursor:])
    return "".join(pieces), numbers


def numeric_template_hash(value: str) -> str | None:
    parts = _numeric_parts(value)
    if parts is None:
        return None
    return hashlib.sha256(parts[0].encode("utf-8")).hexdigest()


def reuse_numeric_translation(
    *, old_source: str, old_translation: str, new_source: str
) -> str | None:
    """Replace preserved numeric literals only when the source skeleton matches.

    If the provider spelled out, converted, dropped, or repeated a number, it
    is safer to translate the new text than to guess where that number belongs.
    """

    old = _numeric_parts(old_source)
    new = _numeric_parts(new_source)
    if old is None or new is None or old[0] != new[0]:
        return None
    translated = old_translation.strip()
    mapping: dict[str, str] = {}
    for previous, current in zip(old[1], new[1], strict=True):
        if previous in mapping and mapping[previous] != current:
            return None
        mapping[previous] = current
    replacements: list[tuple[int, int, str]] = []
    for previous, current in mapping.items():
        pattern = re.compile(
            rf"(?<![A-Za-z0-9.,]){re.escape(previous)}(?![\d.,])"
        )
        occurrences = [
            match
            for match in pattern.finditer(translated)
            if not (suffix := _ASCII_SUFFIX.match(translated, match.end()))
            or suffix.group().casefold() in _NUMERIC_UNITS
        ]
        if len(occurrences) != old[1].count(previous):
            return None
        replacements.extend(
            (match.start(), match.end(), current) for match in occurrences
        )
    spans = sorted(replacements)
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        return None
    for start, end, replacement in reversed(spans):
        translated = translated[:start] + replacement + translated[end:]
    return translated
