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

# A single distinctive word is enough for short chat messages.  The broader
# LANGUAGE_MARKERS table intentionally requires more evidence because it also
# contains ambiguous articles and prepositions such as ``a``, ``la`` and
# ``para``.  Keeping the two groups separate prevents a Chinese storefront
# locale from swallowing common foreign greetings and short product questions.
STRONG_LANGUAGE_MARKERS = {
    "en-US": {
        "hi", "hello", "hey", "thanks", "goodbye", "please", "want", "need",
        "looking", "have", "toy", "toys", "dog", "dogs", "recommend",
    },
    "es": {
        "hola", "gracias", "adiós", "adios", "quiero", "necesito", "busco",
        "tienen", "tienes", "juguete", "juguetes", "perro", "perros", "precio",
        "recomienda", "recomiendas", "recomendación", "cuál", "cuánto",
    },
    "pt": {
        "olá", "ola", "oi", "obrigado", "obrigada", "tchau", "quero",
        "preciso", "procuro", "tem", "têm", "brinquedo", "brinquedos", "cão",
        "cães", "preço", "recomenda", "recomendação",
    },
    "tr": {
        "merhaba", "selam", "teşekkürler", "istiyorum", "arıyorum", "oyuncak",
        "köpek", "fiyat", "öner", "önerir", "tavsiye",
    },
    "fr": {
        "bonjour", "salut", "merci", "veux", "voudrais", "cherche", "avez",
        "jouet", "jouets", "chien", "chiens", "prix", "recommander",
    },
    "de": {
        "hallo", "danke", "tschüss", "möchte", "suche", "haben", "spielzeug",
        "hund", "hunde", "preis", "empfehlen", "empfehlung",
    },
    "it": {
        "ciao", "grazie", "vorrei", "cerco", "avete", "giocattolo", "giocattoli",
        "cane", "cani", "prezzo", "consigliare", "consiglio",
    },
}

EXACT_LANGUAGE_PHRASES = {
    "en-US": {
        "good morning", "good afternoon", "good evening", "thank you",
        "see you", "see you later",
    },
    "es": {"buenos dias", "buenas tardes", "buenas noches", "muchas gracias", "hasta luego"},
    "pt": {"bom dia", "boa tarde", "boa noite", "muito obrigado", "muito obrigada"},
    "tr": {"gunaydin", "iyi aksamlar", "tesekkur ederim", "hosca kal"},
    "fr": {"bonsoir", "merci beaucoup", "au revoir", "a bientot"},
    "de": {"guten morgen", "guten tag", "guten abend", "vielen dank", "auf wiedersehen"},
    "it": {"buon giorno", "buongiorno", "buona sera", "buonasera"},
}

LATIN_LANGUAGE_BASES = {"en", "es", "pt", "tr", "fr", "de", "it"}


def _ascii_fold(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    ).casefold()


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
    natural_text = IDENTIFIER_PATTERN.sub(" ", normalized)
    words = {word.casefold() for word in WORD_PATTERN.findall(natural_text)}
    folded_phrase = " ".join(WORD_PATTERN.findall(_ascii_fold(natural_text)))
    for language, phrases in EXACT_LANGUAGE_PHRASES.items():
        if folded_phrase in phrases:
            return language
    strong_scores = {
        language: len(words & markers)
        for language, markers in STRONG_LANGUAGE_MARKERS.items()
    }
    strongest_language, strongest_score = max(
        strong_scores.items(), key=lambda row: row[1]
    )
    if strongest_score and sum(
        score == strongest_score for score in strong_scores.values()
    ) == 1:
        return strongest_language
    scores = {
        language: len(words & markers)
        for language, markers in LANGUAGE_MARKERS.items()
    }
    language, marker_score = max(scores.items(), key=lambda row: row[1])
    if marker_score >= 2 and sum(
        score == marker_score for score in scores.values()
    ) == 1:
        return language
    hint = locale_hint.strip()
    if words:
        hint_base = hint.replace("_", "-").split("-", 1)[0].casefold()
        if hint_base in LATIN_LANGUAGE_BASES:
            return hint
        # Latin text on a Chinese/Arabic/CJK storefront is still a foreign
        # message. English is the safest first-pass candidate; the generation
        # model is explicitly required to correct this candidate when the
        # vocabulary clearly indicates another Latin-script language.
        return "en-US"
    return hint if hint and hint != "und" else "en-US"


def preserved_identifiers(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in IDENTIFIER_PATTERN.finditer(value)))
