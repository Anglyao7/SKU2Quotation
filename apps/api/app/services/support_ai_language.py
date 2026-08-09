from __future__ import annotations

import re
import unicodedata


WORD_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿİıĞğŞşÇç]+", re.UNICODE)
IDENTIFIER_PATTERN = re.compile(
    r"\b(?=[A-Za-z0-9._/-]{3,40}\b)(?=[A-Za-z0-9._/-]*\d)"
    r"[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)+\b|"
    r"\b[A-Z]{2,}[A-Z0-9-]*\d[A-Z0-9-]*\b"
)

LANGUAGE_MARKERS = {
    "es": {"el", "la", "los", "las", "para", "por", "que", "cuanto", "precio", "producto"},
    "pt": {"o", "a", "os", "as", "para", "por", "que", "quanto", "preco", "produto"},
    "tr": {"bir", "bu", "icin", "için", "nedir", "fiyat", "urun", "ürün", "var", "mi"},
    "fr": {"le", "la", "les", "pour", "avec", "quel", "prix", "produit", "est", "une"},
    "de": {"der", "die", "das", "für", "mit", "welche", "preis", "produkt", "ist", "und"},
    "it": {"il", "la", "gli", "per", "con", "quale", "prezzo", "prodotto", "quanto", "una"},
    "en-US": {"the", "a", "for", "with", "what", "price", "product", "how", "is", "and"},
}


def detect_message_language(value: str, *, locale_hint: str = "und") -> str:
    """Cheap first-pass detection; the generation model performs final confirmation."""

    normalized = unicodedata.normalize("NFKC", value)
    if not normalized.strip():
        return locale_hint or "und"
    counts = {
        "ar": sum(1 for char in normalized if "\u0600" <= char <= "\u06ff"),
        "ru": sum(1 for char in normalized if "\u0400" <= char <= "\u04ff"),
        "ja": sum(1 for char in normalized if "\u3040" <= char <= "\u30ff"),
        "ko": sum(1 for char in normalized if "\uac00" <= char <= "\ud7af"),
        "zh-CN": sum(1 for char in normalized if "\u4e00" <= char <= "\u9fff"),
    }
    script, count = max(counts.items(), key=lambda row: row[1])
    if count:
        # Japanese commonly includes Han characters; kana is the decisive signal.
        if counts["ja"]:
            return "ja"
        if counts["ko"]:
            return "ko"
        return script
    words = {word.casefold() for word in WORD_PATTERN.findall(normalized)}
    scores = {
        language: len(words & markers)
        for language, markers in LANGUAGE_MARKERS.items()
    }
    language, marker_score = max(scores.items(), key=lambda row: row[1])
    if marker_score >= 2:
        return language
    hint = locale_hint.strip()
    return hint if hint and hint != "und" else "en-US"


def preserved_identifiers(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in IDENTIFIER_PATTERN.finditer(value)))

