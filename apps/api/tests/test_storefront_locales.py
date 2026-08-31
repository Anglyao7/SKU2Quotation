from __future__ import annotations

from app.catalog_translation_schemas import CatalogTranslationJobStartRequest
from app.services.quote_localization import (
    localize_quote_unit,
    quote_is_rtl,
    quote_text,
)
from app.services.support_ai_language import detect_message_language
from app.services.translation import LOCALE_NAMES
from app.storefront_locales import (
    SUPPORTED_STOREFRONT_LOCALES,
    effective_storefront_locales,
    normalize_storefront_locale,
)


def test_french_and_persian_are_supported_storefront_locales() -> None:
    assert normalize_storefront_locale("fr-FR") == "fr"
    assert normalize_storefront_locale("fa_IR") == "fa"
    assert SUPPORTED_STOREFRONT_LOCALES[-2:] == ("fr", "fa")
    assert effective_storefront_locales(
        ["fa-IR", "fr-FR", "fa"],
        source_locale="zh-CN",
    ) == ["zh-CN", "fa", "fr"]


def test_french_and_persian_can_start_qwen_batch_translation() -> None:
    for locale in ("fr", "fa"):
        request = CatalogTranslationJobStartRequest(
            target_locale=locale,
            mode="FULL_REBUILD",
            execution_mode="QWEN_BATCH",
            confirm_full_rebuild=True,
        )
        assert request.target_locale == locale
        assert LOCALE_NAMES[locale] in {"French", "Persian"}


def test_quote_localization_supports_french_and_persian_rtl() -> None:
    assert quote_text("fr", "document_title") == "DEVIS"
    assert quote_text("fa", "document_title") == "پیش‌فاکتور"
    assert localize_quote_unit("fr", "piece") == "pces"
    assert localize_quote_unit("fa", "carton") == "کارتن"
    assert quote_is_rtl("fr") is False
    assert quote_is_rtl("fa") is True


def test_persian_script_uses_selected_locale_as_arabic_script_tiebreaker() -> None:
    assert detect_message_language("قیمت این محصول چقدر است؟", locale_hint="fa") == "fa"
    assert detect_message_language("ما سعر هذا المنتج؟", locale_hint="ar") == "ar"
