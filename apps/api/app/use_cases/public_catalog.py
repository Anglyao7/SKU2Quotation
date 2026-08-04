from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..database import set_public_tenant_context, set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import CustomerAccountAccessEventRow, MembershipRow
from ..model_mixins import utcnow
from ..public_catalog_models import (
    PublicQuoteDownloadTokenRow,
    PublicQuoteDraftItemRow,
    PublicQuoteDraftRow,
)
from ..public_catalog_schemas import (
    PUBLIC_DRAFT_DISCLAIMER,
    PUBLIC_DRAFT_DISCLAIMER_VERSION,
    PUBLIC_PRIVACY_NOTICE_VERSION,
    PublicQuoteDocument,
    PublicQuoteDraftCreate,
    PublicQuoteDraftItemResponse,
    PublicQuoteDraftResponse,
    PublicQuoteDraftSummary,
    PublicCategoryOption,
    PublicProductDetail,
    PublicProductPage,
    PublicProductSummary,
    PublicSkuPage,
    PublicSkuResponse,
    PublicStoreResponse,
)
from ..repositories import public_catalog_repository as repository
from ..services.catalog_translation import (
    CatalogTranslationResult,
    catalog_translation_source,
)
from ..services.auth.tokens import hash_secret, new_secret
from ..services.auth.service import AuthError, session_from_access_token
from ..services.embedding import EmbeddingProviderError
from ..services.hybrid_search import _retrieval_tokens, hybrid_product_search
from ..services.rbac import list_permissions
from ..services.translation import (
    TranslationProvider,
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)
from ..services.translation_memory import translate_values_with_memory
from ..storefront_locales import (
    effective_storefront_locales,
    normalize_storefront_locale,
)
from . import announcements as announcement_use_cases
from . import quote_templates as quote_template_use_cases
from . import support as support_use_cases


MONEY = Decimal("0.01")
PUBLIC_TOKEN_SEPARATOR = "."
logger = logging.getLogger(__name__)
_CJK_TEXT_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_TEXT_PATTERN = re.compile(r"[A-Za-z]")
_ENGLISH_FRAGMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Za-z][A-Za-z'’.-]*"
    r"(?:[ \t]+[A-Za-z][A-Za-z'’.-]*)*"
    r"(?![A-Za-z0-9])"
)
_LATIN_OUTPUT_FRAGMENT_PATTERN = re.compile(
    r"(?<![A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F0-9])"
    r"[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F]"
    r"[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F'’.-]*"
    r"(?:[ \t]+[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F]"
    r"[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F'’.-]*)*"
    r"(?![A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F0-9])"
)
_PUBLIC_OPTION_INTERNAL_KEY = "_sku2quotation"
_PUBLIC_OPTION_METADATA_KEYS = frozenset(
    {
        _PUBLIC_OPTION_INTERNAL_KEY,
        "商品编码",
        "商品型号",
        "规格名称",
        "备注",
        "一箱个数",
        "装箱数",
        "毛重",
        "起定数",
        "是否是新品",
    }
)
_NONLINGUISTIC_ENGLISH_FRAGMENTS = frozenset(
    {
        "cm",
        "mm",
        "m",
        "km",
        "g",
        "kg",
        "mg",
        "ml",
        "l",
        "oz",
        "lb",
        "lbs",
        "w",
        "kw",
        "v",
        "mah",
        "hz",
        "pc",
        "pcs",
        "sku",
        "upc",
        "ean",
        "url",
    }
)
_REDUNDANT_BILINGUAL_FIELD_LABEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"ITEM[ \t]*NO\.?|FOLDED[ \t]+SIZE|NET[ \t]+WEIGHT|"
    r"GROSS[ \t]+WEIGHT|MATERIAL|MEAS(?:UREMENTS?)?\.?|"
    r"QUANTITY|QTY\.?|SIZE|N\.?W\.?|G\.?W\.?)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_ENGLISH_CATALOG_TERM_EXPANSIONS = {
    "item no": "Item number",
    "item number": "Item number",
    "nw": "Net weight",
    "n w": "Net weight",
    "net weight": "Net weight",
    "gw": "Gross weight",
    "g w": "Gross weight",
    "gross weight": "Gross weight",
    "meas": "Carton dimensions",
    "measurements": "Carton dimensions",
    "qty": "Quantity",
}
_LIKELY_ENGLISH_CATALOG_WORDS = frozenset(
    {
        "and",
        "automatic",
        "backpack",
        "bag",
        "bear",
        "bed",
        "black",
        "blue",
        "bottle",
        "box",
        "carton",
        "cat",
        "collar",
        "color",
        "dog",
        "doll",
        "electric",
        "feeder",
        "folded",
        "food",
        "for",
        "goods",
        "green",
        "gross",
        "house",
        "item",
        "large",
        "material",
        "medium",
        "normal",
        "number",
        "other",
        "pack",
        "pet",
        "plastic",
        "product",
        "quantity",
        "red",
        "set",
        "size",
        "small",
        "smart",
        "stainless",
        "steel",
        "style",
        "the",
        "to",
        "toy",
        "travel",
        "velvet",
        "water",
        "weight",
        "white",
        "with",
        "without",
    }
)


@dataclass(frozen=True)
class CustomerQuoteSubmitter:
    membership_id: UUID
    tenant_id: UUID
    user_id: UUID


@dataclass(frozen=True)
class PublicProductTranslation:
    name: str
    description: str | None
    category: str | None
    tags: tuple[str, ...]
    display_tag: str | None
    specifications: dict[str, str]
    option_labels: dict[str, str]
    option_values: dict[str, str]
    complete: bool


def optional_customer_quote_submitter(
    identity_session: Session,
    *,
    access_token: str | None,
) -> CustomerQuoteSubmitter | None:
    """Return an active child-account context for an otherwise public quote."""

    if not access_token:
        return None
    try:
        auth_session, user, _claims = session_from_access_token(
            identity_session,
            access_token,
            context_required=True,
        )
    except AuthError:
        return None
    if auth_session.active_membership_id is None:
        return None
    membership = identity_session.get(MembershipRow, auth_session.active_membership_id)
    if (
        membership is None
        or membership.status != "active"
        or membership.account_scope != "CUSTOMER_SUBACCOUNT"
    ):
        return None
    if "customer_portal.order_create" not in list_permissions(
        identity_session,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    ):
        return None
    return CustomerQuoteSubmitter(
        membership_id=membership.id,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _positive_int_environment(name: str, default: int, *, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(value, maximum))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalize_tags(values: list[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        for tag in value.replace("，", ",").split(","):
            normalized = tag.strip().casefold()
            if normalized:
                result.add(normalized)
    return result


def _public_image_url(image: object | None, *, slug: str) -> str | None:
    if image is None:
        return None
    object_key = str(image.object_key).strip()
    if object_key.startswith(("https://", "http://")):
        return object_key
    base = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"{base}/{quote(object_key.lstrip('/'), safe='/')}"
    return f"/api/store/{quote(slug, safe='')}/media/{image.id}"


def _category_path(category: object | None) -> str:
    if category is None:
        return ""
    path = str(getattr(category, "path", "") or "").strip()
    name = str(getattr(category, "name", "") or "").strip()
    code = str(getattr(category, "code", "") or "").strip()
    if path and code and path.casefold() == code.casefold():
        return name
    return path or name


def _normalized_locale(value: str | None, *, default: str = "zh-CN") -> str:
    locale = normalize_storefront_locale(value or default)
    if locale is None:
        raise ApplicationError(
            "PUBLIC_LOCALE_UNSUPPORTED",
            "The requested storefront language is not supported.",
        )
    return locale


def _available_storefront_locales(
    tenant: object,
    profile: object,
) -> list[str]:
    source_locale = _normalized_locale(getattr(tenant, "default_locale", None))
    configured = effective_storefront_locales(
        getattr(profile, "storefront_locales", None),
        source_locale=source_locale,
    )
    if catalog_translation_is_configured():
        return configured
    return [source_locale]


def _requested_storefront_locale(
    locale: str | None,
    *,
    tenant: object,
    profile: object,
) -> tuple[str, str, list[str]]:
    source_locale = _normalized_locale(getattr(tenant, "default_locale", None))
    requested_locale = _normalized_locale(locale, default=source_locale)
    available_locales = _available_storefront_locales(tenant, profile)
    if requested_locale not in available_locales:
        raise ApplicationError(
            "PUBLIC_LOCALE_DISABLED",
            "The requested storefront language is not enabled for this store.",
        )
    return source_locale, requested_locale, available_locales


def _ordered_category_paths(
    visible_category_ids: set[UUID], *, all_categories: list[object]
) -> list[str]:
    categories_by_id = {
        getattr(category, "id"): category
        for category in all_categories
        if getattr(category, "id", None) is not None
    }
    visible_by_id = {
        category_id: categories_by_id[category_id]
        for category_id in visible_category_ids
        if category_id in categories_by_id
        and _category_path(categories_by_id[category_id])
    }

    def sort_key(category: object):
        parent = categories_by_id.get(getattr(category, "parent_id", None))
        root = parent or category
        return (
            int(getattr(root, "sort_order", 0) or 0),
            str(getattr(root, "name", "") or "").casefold(),
            1 if parent is not None else 0,
            int(getattr(category, "sort_order", 0) or 0),
            str(getattr(category, "name", "") or "").casefold(),
        )

    return list(
        dict.fromkeys(
            _category_path(category)
            for category in sorted(visible_by_id.values(), key=sort_key)
        )
    )


def _effective_all_products_position(
    raw_position: int,
    *,
    visible_category_ids: set[UUID],
    all_categories: list[object],
) -> int:
    categories_by_id = {
        getattr(category, "id"): category
        for category in all_categories
        if getattr(category, "id", None) is not None
    }
    visible_root_ids: set[UUID] = set()
    for category_id in visible_category_ids:
        category = categories_by_id.get(category_id)
        if category is None:
            continue
        visible_root_ids.add(
            getattr(category, "parent_id", None) or getattr(category, "id")
        )
    roots = sorted(
        (
            category
            for category in all_categories
            if getattr(category, "parent_id", None) is None
        ),
        key=lambda category: (
            int(getattr(category, "sort_order", 0) or 0),
            str(getattr(category, "name", "") or "").casefold(),
        ),
    )
    cutoff = max(0, min(int(raw_position or 0), len(roots)))
    return sum(
        1
        for category in roots[:cutoff]
        if getattr(category, "id", None) in visible_root_ids
    )


def get_public_media(
    session: Session, *, slug: str, image_id: UUID
) -> tuple[bytes, str]:
    tenant, _profile = _resolve_store(session, slug=slug)
    image = repository.get_approved_public_image(
        session, tenant_id=tenant.id, image_id=image_id
    )
    if image is None:
        raise ApplicationError(
            "PUBLIC_MEDIA_NOT_FOUND", "Public media was not found.", kind="not_found"
        )
    try:
        with get_object_storage().materialize(image.object_key) as path:
            return path.read_bytes(), image.content_type
    except Exception as exc:
        if image.storage_provider == "LOCAL_DEMO":
            placeholder = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" '
                'viewBox="0 0 1200 900"><rect width="1200" height="900" fill="#eee7dc"/>'
                '<path d="M300 650 510 390l150 170 90-110 150 200Z" fill="#c7b6a0"/>'
                '<circle cx="760" cy="290" r="80" fill="#d5c5b1"/>'
                '<text x="600" y="790" text-anchor="middle" font-family="sans-serif" '
                'font-size="38" fill="#6f6559">SKU CATALOG</text></svg>'
            ).encode("utf-8")
            return placeholder, "image/svg+xml"
        raise ApplicationError(
            "PUBLIC_MEDIA_NOT_FOUND", "Public media was not found.", kind="not_found"
        ) from exc


def _resolve_store(session: Session, *, slug: str):
    normalized = slug.casefold().strip()
    profile = repository.find_published_profile_by_slug(session, slug=normalized)
    if profile is None:
        raise ApplicationError("STORE_NOT_FOUND", "Store was not found.", kind="not_found")
    set_public_tenant_context(session, tenant_id=profile.tenant_id)
    tenant = repository.get_active_tenant(
        session, tenant_id=profile.tenant_id
    )
    if tenant is None:
        raise ApplicationError("STORE_NOT_FOUND", "Store was not found.", kind="not_found")
    return tenant, profile


def get_store(
    session: Session,
    *,
    slug: str,
    locale: str | None = None,
) -> PublicStoreResponse:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, available_locales = (
        _requested_storefront_locale(
            locale,
            tenant=tenant,
            profile=profile,
        )
    )
    return PublicStoreResponse(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        description=profile.description,
        logo_url=profile.logo_url,
        contact_email=profile.contact_email,
        contact_phone=profile.contact_phone,
        default_currency=tenant.default_currency,
        locale=requested_locale,
        source_locale=source_locale,
        available_locales=available_locales,
        all_products_position=max(0, int(profile.all_products_position or 0)),
        hot_products_enabled=bool(profile.hot_products_enabled),
        announcements=announcement_use_cases.public_announcements(
            session,
            tenant_id=tenant.id,
        ),
        support_widget=support_use_cases.public_widget(profile),
    )


def _sku_response(
    row: object,
    *,
    image: object | None,
    slug: str,
    category_color: str | None,
    source_locale: str,
    locale: str,
    translation: object | None = None,
) -> PublicSkuResponse:
    offer, sku, product, category = row
    source = catalog_translation_source(row)
    translated = bool(
        translation is not None
        and locale != source_locale
        and getattr(translation, "source_hash", None) == source.source_hash
    )
    translation_complete = bool(
        translated and getattr(translation, "complete", True)
    )
    tags = (
        [
            str(tag).strip()
            for tag in (getattr(translation, "tags", []) or [])
            if str(tag).strip()
        ]
        if translated
        else list(source.tags)
    )
    display_tag = (
        str(getattr(translation, "display_tag", "") or "").strip() or None
        if translated
        else source.display_tag
    )
    return PublicSkuResponse(
        id=sku.id,
        product_id=product.id,
        sku_code=sku.sku_code,
        name=(
            str(getattr(translation, "name", "") or "").strip()
            if translated
            else source.name
        ),
        description=(
            getattr(translation, "description", None)
            if translated
            else source.description
        ),
        category=source.category,
        category_label=(
            str(getattr(translation, "category", "") or "").strip()
            if translated
            else source.category
        )
        or source.category,
        category_color=category_color,
        tags=list(dict.fromkeys(tags)),
        display_tag=(
            display_tag
            if display_tag
            and display_tag.casefold() in {tag.casefold() for tag in tags}
            else tags[0] if tags else None
        ),
        tag_color=offer.tag_color,
        price=_money(Decimal(offer.unit_price)),
        currency=offer.currency,
        unit_code=product.default_unit or "piece",
        image_url=_public_image_url(image, slug=slug),
        product_version=product.current_version,
        sku_version=sku.version,
        specification=(
            str((sku.option_values or {}).get("规格名称") or "").strip()
            or None
        ),
        option_values=dict(sku.option_values or {}),
        source_locale=source_locale,
        locale=locale,
        translation_status=(
            "SOURCE"
            if locale == source_locale
            else "TRANSLATED"
            if translation_complete
            else "FALLBACK"
        ),
    )


def _live_translation_provider(
    *,
    source_locale: str,
    target_locale: str,
) -> TranslationProvider | None:
    if target_locale == source_locale:
        return None
    try:
        return configured_catalog_translator()
    except TranslationProviderError as exc:
        logger.warning("live catalog translation is unavailable: %s", exc)
        return None


def _is_translatable_catalog_text(value: str) -> bool:
    return bool(
        value.strip()
        and (
            _CJK_TEXT_PATTERN.search(value)
            or _LATIN_TEXT_PATTERN.search(value)
        )
    )


def _is_nonlinguistic_english_fragment(value: str) -> bool:
    letters = "".join(character for character in value if character.isalpha())
    return (
        value.casefold() in _NONLINGUISTIC_ENGLISH_FRAGMENTS
        or (
            bool(letters)
            and len(letters) <= 4
            and value.replace(".", "").isalpha()
            and value.upper() == value
        )
    )


def _latin_fragments(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            fragment
            for match in _LATIN_OUTPUT_FRAGMENT_PATTERN.finditer(value)
            if (
                (fragment := match.group(0).strip())
                and not _is_nonlinguistic_english_fragment(fragment)
            )
        )
    )


def _english_fragments(value: str) -> tuple[str, ...]:
    """Return natural-language Latin fragments embedded in CJK catalog text.

    DeepLX correctly translates the Chinese portion of mixed strings but can
    leave labels such as ``ITEM NO`` untouched when the source language is
    Chinese. Units and catalog identifiers are deliberately not treated as
    prose; the lower-level translator already protects alpha-numeric codes.
    """

    if not _CJK_TEXT_PATTERN.search(value):
        return ()
    return tuple(
        dict.fromkeys(
            fragment
            for match in _ENGLISH_FRAGMENT_PATTERN.finditer(value)
            if (
                (fragment := match.group(0).strip())
                and not _is_nonlinguistic_english_fragment(fragment)
            )
        )
    )


def _replace_english_fragment(
    value: str,
    *,
    source: str,
    translated: str,
) -> str:
    if not source or not translated or source.casefold() == translated.casefold():
        return value
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return pattern.sub(lambda _match: translated, value)


def _prepare_catalog_translation_value(value: str) -> str:
    if not _CJK_TEXT_PATTERN.search(value):
        return value.strip()
    prepared = _REDUNDANT_BILINGUAL_FIELD_LABEL_PATTERN.sub("", value)
    prepared = re.sub(r"[ \t]+(?=[:：])", "", prepared)
    prepared = re.sub(r"[ \t]{2,}", " ", prepared)
    return prepared.strip()


def _expanded_english_catalog_term(value: str) -> str:
    normalized = re.sub(r"[.\s]+", " ", value).strip().casefold()
    return _ENGLISH_CATALOG_TERM_EXPANSIONS.get(normalized, value)


def _looks_likely_english_catalog_fragment(value: str) -> bool:
    words = {
        word.casefold()
        for word in re.findall(r"[A-Za-z]{2,}", value)
    }
    return bool(words & _LIKELY_ENGLISH_CATALOG_WORDS)


def _translate_english_catalog_fragments(
    *,
    tenant_id: UUID,
    translator: TranslationProvider,
    fragments: list[str],
    target_locale: str,
) -> dict[str, str]:
    expanded_by_fragment = {
        fragment: _expanded_english_catalog_term(fragment)
        for fragment in fragments
    }
    translated_expansions = translate_values_with_memory(
        tenant_id=tenant_id,
        translator=translator,
        values=list(dict.fromkeys(expanded_by_fragment.values())),
        source_locale="en-US",
        target_locale=target_locale,
    )
    return {
        fragment: translated_expansions[expanded]
        for fragment, expanded in expanded_by_fragment.items()
        if expanded in translated_expansions
    }


def _translate_public_catalog_values(
    *,
    tenant_id: UUID,
    translator: TranslationProvider,
    values: list[str],
    source_locale: str,
    target_locale: str,
    normalize_provider_output: bool = False,
) -> tuple[dict[str, str], set[str]]:
    """Translate Chinese, English and mixed storefront content completely.

    Whole values retain their context and formatting. Pure English values are
    translated with an English source language; mixed Chinese/English values
    are translated as Chinese first, then any English fragment that survives
    verbatim receives a small cached English-to-target repair pass.
    """

    source_values = list(
        dict.fromkeys(
            value.strip()
            for value in values
            if _is_translatable_catalog_text(value)
        )
    )
    if not source_values:
        return {}, set()
    prepared_by_source = {
        source_value: _prepare_catalog_translation_value(source_value)
        for source_value in source_values
    }
    unique_values = list(dict.fromkeys(prepared_by_source.values()))

    grouped_values: dict[str, list[str]] = {}
    translated_values: dict[str, str] = {}
    complete_values: set[str] = set()
    for value in unique_values:
        value_source_locale = (
            source_locale
            if _CJK_TEXT_PATTERN.search(value)
            else "en-US"
        )
        if value_source_locale == target_locale:
            translated_values[value] = value
            complete_values.add(value)
            continue
        grouped_values.setdefault(value_source_locale, []).append(value)

    for value_source_locale, source_values in grouped_values.items():
        translated_group = translate_values_with_memory(
            tenant_id=tenant_id,
            translator=translator,
            values=source_values,
            source_locale=value_source_locale,
            target_locale=target_locale,
        )
        translated_values.update(translated_group)
        complete_values.update(translated_group)

    if target_locale not in {"en", "en-US"}:
        residual_fragments_by_value: dict[str, tuple[str, ...]] = {}
        for source_value in unique_values:
            translated_value = translated_values.get(source_value)
            if translated_value is None:
                continue
            residuals = tuple(
                fragment
                for fragment in _english_fragments(source_value)
                if re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(fragment)}(?![A-Za-z0-9])",
                    translated_value,
                    re.IGNORECASE,
                )
            )
            if residuals:
                residual_fragments_by_value[source_value] = residuals

        residual_fragments = list(
            dict.fromkeys(
                fragment
                for fragments in residual_fragments_by_value.values()
                for fragment in fragments
            )
        )
        fragment_translations = (
            _translate_english_catalog_fragments(
                tenant_id=tenant_id,
                translator=translator,
                fragments=residual_fragments,
                target_locale=target_locale,
            )
            if residual_fragments
            else {}
        )
        for source_value, residuals in residual_fragments_by_value.items():
            localized = translated_values[source_value]
            for fragment in sorted(residuals, key=len, reverse=True):
                fragment_translation = fragment_translations.get(fragment)
                if fragment_translation is None:
                    complete_values.discard(source_value)
                    continue
                localized = _replace_english_fragment(
                    localized,
                    source=fragment,
                    translated=fragment_translation,
                )
            translated_values[source_value] = localized

        # DeepLX can occasionally translate a Chinese title into English even
        # when another target language was requested (for example
        # ``MC宠物包`` -> ``MC Pet Pack`` for Portuguese). Re-run the Latin
        # phrases from the provider output as a compact English-to-target
        # normalization pass. Phrases already written in the target language
        # are returned unchanged by DeepLX and therefore remain untouched.
        output_fragments_by_value = (
            {
                source_value: tuple(
                    fragment
                    for fragment in _latin_fragments(localized)
                    if _looks_likely_english_catalog_fragment(fragment)
                )
                for source_value, localized in translated_values.items()
                if any(
                    _looks_likely_english_catalog_fragment(fragment)
                    for fragment in _latin_fragments(localized)
                )
            }
            if normalize_provider_output
            else {}
        )
        output_fragments = list(
            dict.fromkeys(
                fragment
                for fragments in output_fragments_by_value.values()
                for fragment in fragments
            )
        )
        output_fragment_translations = (
            _translate_english_catalog_fragments(
                tenant_id=tenant_id,
                translator=translator,
                fragments=output_fragments,
                target_locale=target_locale,
            )
            if output_fragments
            else {}
        )
        for source_value, fragments in output_fragments_by_value.items():
            localized = translated_values[source_value]
            for fragment in sorted(fragments, key=len, reverse=True):
                fragment_translation = output_fragment_translations.get(fragment)
                if fragment_translation is None:
                    continue
                localized = _replace_english_fragment(
                    localized,
                    source=fragment,
                    translated=fragment_translation,
                )
            translated_values[source_value] = localized

    localized_by_source = {
        source_value: translated_values[prepared]
        for source_value, prepared in prepared_by_source.items()
        if prepared in translated_values
    }
    complete_sources = {
        source_value
        for source_value, prepared in prepared_by_source.items()
        if prepared in complete_values
    }
    for original in values:
        normalized = original.strip()
        if original != normalized and normalized in localized_by_source:
            localized_by_source[original] = localized_by_source[normalized]
        if normalized in complete_sources:
            complete_sources.add(original)
    return localized_by_source, complete_sources


def _public_option_text(value: object) -> str | None:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (str, int, float, Decimal)):
        normalized = str(value).strip()
        return normalized or None
    return None


def _public_variant_option_keys(rows: list[object]) -> tuple[str, ...]:
    explicit: list[str] = []
    for row in rows:
        option_values = row[1].option_values or {}
        marker = option_values.get(_PUBLIC_OPTION_INTERNAL_KEY)
        marker_keys = (
            marker.get("variant_option_keys", [])
            if isinstance(marker, dict)
            else []
        )
        for key in marker_keys:
            normalized = str(key).strip() if isinstance(key, str) else ""
            if normalized and normalized not in explicit:
                explicit.append(normalized)
    if explicit:
        return tuple(explicit)

    discovered: list[str] = []
    for row in rows:
        for key, value in (row[1].option_values or {}).items():
            normalized = str(key).strip()
            if (
                normalized
                and normalized not in _PUBLIC_OPTION_METADATA_KEYS
                and not normalized.startswith("_")
                and _public_option_text(value) is not None
                and normalized not in discovered
            ):
                discovered.append(normalized)
    return tuple(discovered)


def _localized_public_option_values(
    option_values: dict[str, object],
    *,
    translation: PublicProductTranslation | None,
) -> dict[str, object]:
    localized = dict(option_values)
    if translation is None or not translation.option_labels:
        return localized

    marker = localized.get(_PUBLIC_OPTION_INTERNAL_KEY)
    localized_marker = dict(marker) if isinstance(marker, dict) else None
    marker_keys = (
        [
            str(key).strip()
            for key in localized_marker.get("variant_option_keys", [])
            if isinstance(key, str) and str(key).strip()
        ]
        if localized_marker is not None
        else []
    )
    localized_key_by_source: dict[str, str] = {}
    for source_key, translated_key in translation.option_labels.items():
        if source_key not in localized:
            continue
        source_value = localized.pop(source_key)
        destination_key = translated_key.strip() or source_key
        if destination_key in localized:
            destination_key = source_key
        source_text = _public_option_text(source_value)
        localized[destination_key] = (
            translation.option_values.get(source_text, source_value)
            if source_text is not None
            else source_value
        )
        localized_key_by_source[source_key] = destination_key

    if localized_marker is not None:
        if marker_keys:
            localized_marker["variant_option_keys"] = [
                localized_key_by_source.get(
                    marker_key,
                    translation.option_labels.get(marker_key, marker_key),
                )
                for marker_key in marker_keys
            ]
        localized[_PUBLIC_OPTION_INTERNAL_KEY] = localized_marker
    return localized


def _live_sku_translation_map(
    rows: list[object],
    *,
    tenant_id: UUID,
    translator: TranslationProvider | None,
    source_locale: str,
    target_locale: str,
    additional_values: list[str] | None = None,
) -> dict[UUID, CatalogTranslationResult]:
    if translator is None or not rows:
        return {}
    sources = [catalog_translation_source(row) for row in rows]
    names = [source.name for source in sources]
    description_parts: list[list[tuple[str, str, bool]]] = []
    translation_values: list[str] = [
        name for name in names if _is_translatable_catalog_text(name)
    ]
    for source in sources:
        parts: list[tuple[str, str, bool]] = []
        for raw_line in (source.description or "").splitlines(keepends=True):
            if raw_line.endswith("\r\n"):
                content, ending = raw_line[:-2], "\r\n"
            elif raw_line.endswith(("\r", "\n")):
                content, ending = raw_line[:-1], raw_line[-1:]
            else:
                content, ending = raw_line, ""
            needs_translation = _is_translatable_catalog_text(content)
            parts.append((content, ending, needs_translation))
            if needs_translation:
                translation_values.append(content)
        description_parts.append(parts)

    metadata_candidates: list[str] = []
    for source in sources:
        metadata_candidates.extend(
            segment.strip()
            for segment in (source.category or "")
            .replace("／", "/")
            .split("/")
            if segment.strip()
        )
        metadata_candidates.extend(source.tags)
    metadata_candidates.extend(additional_values or [])
    translation_values.extend(
        value
        for value in metadata_candidates
        if _is_translatable_catalog_text(value)
    )
    translated_values, complete_values = _translate_public_catalog_values(
        tenant_id=tenant_id,
        translator=translator,
        values=list(dict.fromkeys(translation_values)),
        source_locale=source_locale,
        target_locale=target_locale,
        normalize_provider_output=True,
    )
    names = [translated_values.get(name, name) for name in names]

    descriptions: list[str | None] = []
    for source, parts in zip(sources, description_parts, strict=True):
        if source.description is None:
            descriptions.append(None)
            continue
        descriptions.append(
            "".join(
                (
                    translated_values.get(content, content)
                    if needs_translation
                    else content
                )
                + ending
                for content, ending, needs_translation in parts
            )
        )
    metadata_labels = {
        value: translated_values.get(value, value)
        for value in metadata_candidates
    }

    results: dict[UUID, CatalogTranslationResult] = {}
    for index, source in enumerate(sources):
        category_segments = [
            segment.strip()
            for segment in (source.category or "")
            .replace("／", "/")
            .split("/")
            if segment.strip()
        ]
        translated_tags = tuple(
            metadata_labels.get(tag, tag)
            for tag in source.tags
        )
        display_tag_index = next(
            (
                tag_index
                for tag_index, tag in enumerate(source.tags)
                if source.display_tag
                and tag.casefold() == source.display_tag.casefold()
            ),
            None,
        )
        required_values = [
            value
            for value in (
                source.name,
                *(
                    content
                    for content, _ending, needs_translation in description_parts[
                        index
                    ]
                    if needs_translation
                ),
                *category_segments,
                *source.tags,
            )
            if _is_translatable_catalog_text(value)
        ]
        results[source.sku_id] = CatalogTranslationResult(
            sku_id=source.sku_id,
            source_hash=source.source_hash,
            name=names[index],
            description=descriptions[index],
            category=(
                "/".join(
                    metadata_labels.get(segment, segment)
                    for segment in category_segments
                )
                or None
            ),
            tags=translated_tags,
            display_tag=(
                translated_tags[display_tag_index]
                if display_tag_index is not None
                else translated_tags[0] if translated_tags else None
            ),
            complete=all(
                value.strip() in complete_values
                for value in required_values
            ),
        )
    return results


def _live_category_labels(
    categories: list[str],
    *,
    tenant_id: UUID,
    translator: TranslationProvider | None,
    source_locale: str,
    target_locale: str,
) -> dict[str, str]:
    if translator is None or not categories:
        return {}
    segments = list(
        dict.fromkeys(
            segment.strip()
            for category in categories
            for segment in category.replace("／", "/").split("/")
            if segment.strip()
        )
    )
    translated_segments, _complete_segments = _translate_public_catalog_values(
        tenant_id=tenant_id,
        translator=translator,
        values=[
            segment
            for segment in segments
            if _is_translatable_catalog_text(segment)
        ],
        source_locale=source_locale,
        target_locale=target_locale,
    )
    return {
        category: "/".join(
            translated_segments.get(segment.strip(), segment.strip())
            for segment in category.replace("／", "/").split("/")
            if segment.strip()
        )
        for category in categories
    }


def _group_catalog_rows(
    rows: list[object],
    *,
    product_ids: list[UUID] | None = None,
) -> list[list[object]]:
    grouped: dict[UUID, list[object]] = {}
    for row in rows:
        grouped.setdefault(row[2].id, []).append(row)
    ordered_ids = product_ids or list(grouped)
    return [grouped[product_id] for product_id in ordered_ids if product_id in grouped]


def _product_group_tags(rows: list[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(tag).strip()
            for row in rows
            for tag in (row[0].tags or [])
            if str(tag).strip()
        )
    )


def _product_group_display_tag(
    rows: list[object],
    *,
    tags: tuple[str, ...],
) -> str | None:
    tag_lookup = {tag.casefold(): tag for tag in tags}
    return next(
        (
            tag_lookup.get(str(row[0].display_tag or "").strip().casefold())
            for row in rows
            if str(row[0].display_tag or "").strip()
            and tag_lookup.get(
                str(row[0].display_tag or "").strip().casefold()
            )
        ),
        tags[0] if tags else None,
    )


def _live_product_translation_map(
    groups: list[list[object]],
    *,
    tenant_id: UUID,
    translator: TranslationProvider | None,
    source_locale: str,
    target_locale: str,
    include_sku_options: bool = False,
) -> dict[UUID, PublicProductTranslation]:
    if translator is None or not groups:
        return {}
    translation_values: list[str] = []
    sources: list[dict[str, object]] = []
    for rows in groups:
        _offer, _sku, product, category = rows[0]
        tags = _product_group_tags(rows)
        display_tag = _product_group_display_tag(rows, tags=tags)
        category_segments = [
            segment.strip()
            for segment in _category_path(category)
            .replace("／", "/")
            .split("/")
            if segment.strip()
        ]
        description_parts: list[tuple[str, str, bool]] = []
        for raw_line in str(product.description or "").splitlines(keepends=True):
            if raw_line.endswith("\r\n"):
                content, ending = raw_line[:-2], "\r\n"
            elif raw_line.endswith(("\r", "\n")):
                content, ending = raw_line[:-1], raw_line[-1:]
            else:
                content, ending = raw_line, ""
            needs_translation = _is_translatable_catalog_text(content)
            description_parts.append((content, ending, needs_translation))
            if needs_translation:
                translation_values.append(content)
        specifications = tuple(
            dict.fromkeys(
                str((row[1].option_values or {}).get("规格名称") or "").strip()
                for row in rows
                if str(
                    (row[1].option_values or {}).get("规格名称") or ""
                ).strip()
            )
        )
        option_labels = (
            _public_variant_option_keys(rows)
            if include_sku_options
            else ()
        )
        option_choice_values = tuple(
            dict.fromkeys(
                option_text
                for row in rows
                for option_label in option_labels
                if (
                    option_text := _public_option_text(
                        (row[1].option_values or {}).get(option_label)
                    )
                )
            )
        )
        values = [
            str(product.name).strip(),
            *category_segments,
            *tags,
            *specifications,
            *option_labels,
            *option_choice_values,
        ]
        translation_values.extend(
            value for value in values if _is_translatable_catalog_text(value)
        )
        sources.append(
            {
                "product_id": product.id,
                "name": str(product.name).strip(),
                "description": str(product.description or "").strip() or None,
                "description_parts": description_parts,
                "category_segments": category_segments,
                "tags": tags,
                "display_tag": display_tag,
                "specifications": specifications,
                "option_labels": option_labels,
                "option_choice_values": option_choice_values,
            }
        )

    translated_values, complete_values = _translate_public_catalog_values(
        tenant_id=tenant_id,
        translator=translator,
        values=list(dict.fromkeys(translation_values)),
        source_locale=source_locale,
        target_locale=target_locale,
        normalize_provider_output=True,
    )
    results: dict[UUID, PublicProductTranslation] = {}
    for source in sources:
        name = str(source["name"])
        description = source["description"]
        description_parts = source["description_parts"]
        category_segments = source["category_segments"]
        tags = source["tags"]
        display_tag = source["display_tag"]
        specifications = source["specifications"]
        option_labels = source["option_labels"]
        option_choice_values = source["option_choice_values"]
        translated_tags = tuple(
            translated_values.get(tag, tag) for tag in tags
        )
        display_tag_index = next(
            (
                index
                for index, tag in enumerate(tags)
                if display_tag and tag.casefold() == display_tag.casefold()
            ),
            None,
        )
        required_values = [
            value
            for value in (
                name,
                *(
                    content
                    for content, _ending, needs_translation in description_parts
                    if needs_translation
                ),
                *category_segments,
                *tags,
                *specifications,
                *option_labels,
                *option_choice_values,
            )
            if _is_translatable_catalog_text(value)
        ]
        results[source["product_id"]] = PublicProductTranslation(
            name=translated_values.get(name, name),
            description=(
                "".join(
                    (
                        translated_values.get(content, content)
                        if needs_translation
                        else content
                    )
                    + ending
                    for content, ending, needs_translation in description_parts
                )
                if description is not None
                else None
            ),
            category=(
                "/".join(
                    translated_values.get(segment, segment)
                    for segment in category_segments
                )
                or None
            ),
            tags=translated_tags,
            display_tag=(
                translated_tags[display_tag_index]
                if display_tag_index is not None
                else translated_tags[0] if translated_tags else None
            ),
            specifications={
                specification: translated_values.get(
                    specification,
                    specification,
                )
                for specification in specifications
            },
            option_labels={
                option_label: translated_values.get(
                    option_label,
                    option_label,
                )
                for option_label in option_labels
            },
            option_values={
                option_value: translated_values.get(
                    option_value,
                    option_value,
                )
                for option_value in option_choice_values
            },
            complete=all(
                value.strip() in complete_values for value in required_values
            ),
        )
    return results


def _product_summary_response(
    rows: list[object],
    *,
    image: object | None,
    slug: str,
    category_color: str | None,
    source_locale: str,
    locale: str,
    translation: PublicProductTranslation | None,
) -> PublicProductSummary:
    _offer, first_sku, product, category = rows[0]
    tags = _product_group_tags(rows)
    display_tag = _product_group_display_tag(rows, tags=tags)
    translated = translation is not None and locale != source_locale
    prices = [_money(Decimal(row[0].unit_price)) for row in rows]
    currencies = [str(row[0].currency) for row in rows]
    product_model = str(
        (first_sku.option_values or {}).get("商品型号") or ""
    ).strip()
    public_product_code = (
        product_model
        or (
            str(first_sku.sku_code)
            if str(product.product_code).startswith(("TPL-", "TPLX-"))
            else str(product.product_code)
        )
    )
    tag_color = next(
        (
            str(row[0].tag_color)
            for row in rows
            if row[0].tag_color
        ),
        None,
    )
    return PublicProductSummary(
        id=product.id,
        product_code=public_product_code,
        name=translation.name if translated else str(product.name),
        description=(
            translation.description
            if translated
            else str(product.description or "").strip() or None
        ),
        category=_category_path(category) or None,
        category_label=(
            translation.category
            if translated
            else _category_path(category) or None
        ),
        category_color=category_color,
        tags=list(translation.tags if translated else tags),
        display_tag=translation.display_tag if translated else display_tag,
        tag_color=tag_color,
        price_from=min(prices),
        price_to=max(prices),
        currency=currencies[0],
        unit_code=product.default_unit or "piece",
        image_url=_public_image_url(image, slug=slug),
        sku_count=len({row[1].id for row in rows}),
        product_version=product.current_version,
        source_locale=source_locale,
        locale=locale,
        translation_status=(
            "SOURCE"
            if locale == source_locale
            else "TRANSLATED"
            if translation is not None and translation.complete
            else "FALLBACK"
        ),
    )


def _lexical_semantic_rows(rows: list[object], *, query: str) -> list[object]:
    normalized_query = query.casefold().strip()
    query_tokens = _retrieval_tokens(query, query=True)

    def relevance(row: object) -> float:
        offer, sku, product, row_category = row
        sku_code = str(sku.sku_code).casefold()
        sku_name = str(sku.name or "").casefold()
        product_name = str(product.name).casefold()
        description = str(product.description or "").casefold()
        category_name = _category_path(row_category).casefold()
        tag_values = [str(tag).casefold() for tag in (offer.tags or [])]
        fields = [
            sku_code,
            sku_name,
            product_name,
            description,
            category_name,
            *tag_values,
        ]
        searchable_tokens = _retrieval_tokens(" ".join(fields))
        coverage = (
            len(query_tokens & searchable_tokens) / len(query_tokens)
            if query_tokens
            else 0.0
        )
        score = coverage
        if sku_code == normalized_query:
            score += 2.0
        elif normalized_query in sku_code:
            score += 0.8
        if normalized_query in sku_name or normalized_query in product_name:
            score += 0.6
        if any(normalized_query in tag for tag in tag_values):
            score += 0.5
        return score

    scored = [(relevance(row), row) for row in rows]
    best_score = max((score for score, _row in scored), default=0.0)
    score_floor = max(0.12, best_score * 0.50)
    return [
        row
        for score, row in sorted(
            scored,
            key=lambda item: (
                -item[0],
                str(item[1][2].name).casefold(),
                str(item[1][1].sku_code).casefold(),
            ),
        )
        if score >= score_floor
    ]


def _bounded_public_lexical_rows(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    now: datetime,
    category: str | None,
) -> list[object]:
    normalized_query = query.casefold().strip()
    tokens = sorted(
        (
            token
            for token in _retrieval_tokens(query, query=True)
            if len(token) >= 2 or token.isascii()
        ),
        key=lambda token: (-len(token), token),
    )
    terms = list(dict.fromkeys([normalized_query, *tokens]))[:16]
    rows = repository.list_public_catalog_lexical_candidates(
        session,
        tenant_id=tenant_id,
        now=now,
        query=query,
        terms=terms,
        category=category,
        limit=_positive_int_environment(
            "PUBLIC_LEXICAL_CANDIDATE_LIMIT",
            1_000,
            maximum=5_000,
        ),
    )
    return _lexical_semantic_rows(rows, query=query)


def _vector_semantic_rows(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    now: datetime,
    category: str | None,
) -> list[object]:
    result_limit = _positive_int_environment(
        "PUBLIC_SEMANTIC_RESULT_LIMIT",
        200,
        maximum=500,
    )
    result = hybrid_product_search(
        session,
        tenant_id=tenant_id,
        query=query,
        limit=result_limit,
    )
    product_ids = [
        item["product_id"] for item in result["results"]
    ]
    rows = repository.list_public_catalog_rows_by_product_ids(
        session,
        tenant_id=tenant_id,
        product_ids=product_ids,
        now=now,
        category=category,
    )
    if not result["results"]:
        return _bounded_public_lexical_rows(
            session,
            tenant_id=tenant_id,
            query=query,
            now=now,
            category=category,
        )
    rank_by_product_id = {
        item["product_id"]: index
        for index, item in enumerate(result["results"])
    }
    return sorted(
        (
            row
            for row in rows
            if row[2].id in rank_by_product_id
        ),
        key=lambda row: (
            rank_by_product_id[row[2].id],
            str(row[1].sku_code).casefold(),
        ),
    )


def list_public_products(
    session: Session,
    *,
    slug: str,
    query: str,
    category: str | None,
    tags: list[str],
    semantic: bool,
    include_facets: bool,
    page: int,
    page_size: int,
    locale: str | None = None,
) -> PublicProductPage:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            locale,
            tenant=tenant,
            profile=profile,
        )
    )
    now = utcnow()
    wanted_tags = _normalize_tags(tags)
    hot_sort_applied = bool(
        profile.hot_products_enabled
        and not query.strip()
        and not (category or "").strip()
        and not wanted_tags
        and not semantic
    )
    all_categories = (
        repository.list_catalog_categories(session, tenant_id=tenant.id)
        if include_facets
        else []
    )

    if semantic and query.strip():
        try:
            candidate_rows = _vector_semantic_rows(
                session,
                tenant_id=tenant.id,
                query=query,
                now=now,
                category=category,
            )
        except EmbeddingProviderError:
            candidate_rows = _bounded_public_lexical_rows(
                session,
                tenant_id=tenant.id,
                query=query,
                now=now,
                category=category,
            )
        if wanted_tags:
            candidate_rows = [
                row
                for row in candidate_rows
                if wanted_tags.issubset(
                    {
                        str(tag).strip().casefold()
                        for tag in (row[0].tags or [])
                    }
                )
            ]
        matching_product_ids = list(
            dict.fromkeys(row[2].id for row in candidate_rows)
        )
        total = len(matching_product_ids)
        start = (page - 1) * page_size
        selected_product_ids = matching_product_ids[start : start + page_size]
    else:
        total = repository.count_public_catalog_products(
            session,
            tenant_id=tenant.id,
            now=now,
            query=query,
            category=category,
            tags=wanted_tags,
        )
        selected_product_ids = repository.list_public_product_ids_page(
            session,
            tenant_id=tenant.id,
            now=now,
            query=query,
            category=category,
            tags=wanted_tags,
            page=page,
            page_size=page_size,
            hot=hot_sort_applied,
        )

    selected_rows = repository.list_public_catalog_rows_by_product_ids(
        session,
        tenant_id=tenant.id,
        product_ids=selected_product_ids,
        now=now,
        category=category,
    )
    groups = _group_catalog_rows(
        selected_rows,
        product_ids=selected_product_ids,
    )
    if include_facets:
        visible_category_ids = repository.list_public_catalog_category_ids(
            session,
            tenant_id=tenant.id,
            now=now,
            query="",
            category=None,
        )
    else:
        visible_category_ids = set()
    categories = _ordered_category_paths(
        visible_category_ids,
        all_categories=all_categories,
    )
    category_rows_by_id = {row.id: row for row in all_categories}
    category_colors_by_id = {
        row.id: (
            row.display_color
            if row.parent_id is None
            else category_rows_by_id.get(row.parent_id).display_color
            if category_rows_by_id.get(row.parent_id) is not None
            else None
        )
        for row in all_categories
    }
    images = repository.approved_image_map(
        session,
        tenant_id=tenant.id,
        product_ids=set(selected_product_ids),
    )
    translator = _live_translation_provider(
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    translations = _live_product_translation_map(
        groups,
        tenant_id=tenant.id,
        translator=translator,
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    category_labels = (
        _live_category_labels(
            categories,
            tenant_id=tenant.id,
            translator=translator,
            source_locale=source_locale,
            target_locale=requested_locale,
        )
        if requested_locale != source_locale and include_facets
        else {}
    )
    return PublicProductPage(
        items=[
            _product_summary_response(
                rows,
                image=images.get(rows[0][2].id),
                slug=tenant.slug,
                category_color=(
                    category_colors_by_id.get(rows[0][3].id)
                    if rows[0][3] is not None
                    else None
                ),
                source_locale=source_locale,
                locale=requested_locale,
                translation=translations.get(rows[0][2].id),
            )
            for rows in groups
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        categories=categories,
        category_options=[
            PublicCategoryOption(
                value=category_path,
                label=category_labels.get(category_path, category_path),
            )
            for category_path in categories
        ],
        # Product tags remain part of each product and semantic-search input.
        # The storefront no longer renders a global tag facet, so avoid a
        # full-catalog scan solely to populate unused chips.
        tags=[],
        source_locale=source_locale,
        locale=requested_locale,
        all_products_position=(
            _effective_all_products_position(
                profile.all_products_position,
                visible_category_ids=visible_category_ids,
                all_categories=all_categories,
            )
            if include_facets
            else 0
        ),
        hot_products_enabled=bool(profile.hot_products_enabled),
        hot_sort_applied=hot_sort_applied,
    )


def get_public_product(
    session: Session,
    *,
    slug: str,
    product_id: UUID,
    locale: str | None = None,
) -> PublicProductDetail:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            locale,
            tenant=tenant,
            profile=profile,
        )
    )
    rows = repository.list_public_catalog_rows_by_product_ids(
        session,
        tenant_id=tenant.id,
        product_ids=[product_id],
        now=utcnow(),
        category=None,
    )
    if not rows:
        raise ApplicationError(
            "PUBLIC_PRODUCT_NOT_FOUND",
            "Public product was not found.",
            kind="not_found",
        )
    category = rows[0][3]
    root_category = (
        repository.get_catalog_category(
            session,
            tenant_id=tenant.id,
            category_id=category.parent_id,
        )
        if category is not None and category.parent_id is not None
        else category
    )
    image = repository.approved_image_for_product(
        session,
        tenant_id=tenant.id,
        product_id=product_id,
    )
    translator = _live_translation_provider(
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    product_translations = _live_product_translation_map(
        [rows],
        tenant_id=tenant.id,
        translator=translator,
        source_locale=source_locale,
        target_locale=requested_locale,
        include_sku_options=True,
    )
    product_translation = product_translations.get(product_id)
    summary = _product_summary_response(
        rows,
        image=image,
        slug=tenant.slug,
        category_color=(
            root_category.display_color
            if root_category is not None
            else None
        ),
        source_locale=source_locale,
        locale=requested_locale,
        translation=product_translation,
    )
    source_group_tags = _product_group_tags(rows)
    translated_tag_by_source = (
        {
            source_tag.casefold(): translated_tag
            for source_tag, translated_tag in zip(
                source_group_tags,
                product_translation.tags,
            )
        }
        if product_translation is not None
        else {}
    )
    skus: list[PublicSkuResponse] = []
    for row in sorted(
        rows,
        key=lambda item: (
            str((item[1].option_values or {}).get("规格名称") or "").casefold(),
            str(item[1].sku_code).casefold(),
        ),
    ):
        response = _sku_response(
            row,
            image=image,
            slug=tenant.slug,
            category_color=summary.category_color,
            source_locale=source_locale,
            locale=requested_locale,
            translation=None,
        )
        source_specification = str(
            (row[1].option_values or {}).get("规格名称") or ""
        ).strip()
        specification = (
            product_translation.specifications.get(
                source_specification,
                source_specification,
            )
            if product_translation is not None and source_specification
            else source_specification or None
        )
        localized_option_values = _localized_public_option_values(
            dict(row[1].option_values or {}),
            translation=(
                product_translation
                if requested_locale != source_locale
                else None
            ),
        )
        if specification:
            localized_option_values["规格名称"] = specification
        source_sku_tags = tuple(
            dict.fromkeys(
                str(tag).strip()
                for tag in (row[0].tags or [])
                if str(tag).strip()
            )
        )
        localized_sku_tags = [
            translated_tag_by_source.get(tag.casefold(), tag)
            for tag in source_sku_tags
        ]
        source_display_tag = str(row[0].display_tag or "").strip()
        localized_display_tag = (
            translated_tag_by_source.get(
                source_display_tag.casefold(),
                source_display_tag,
            )
            if source_display_tag
            else localized_sku_tags[0] if localized_sku_tags else None
        )
        if (
            localized_display_tag
            and localized_display_tag.casefold()
            not in {tag.casefold() for tag in localized_sku_tags}
        ):
            localized_display_tag = (
                localized_sku_tags[0] if localized_sku_tags else None
            )
        response = response.model_copy(
            update={
                "name": (
                    f"{summary.name} · {specification}"
                    if specification
                    else summary.name
                ),
                "description": summary.description,
                "category_label": summary.category_label,
                "tags": localized_sku_tags,
                "display_tag": localized_display_tag,
                "specification": specification,
                "option_values": localized_option_values,
                "locale": requested_locale,
                "translation_status": summary.translation_status,
            }
        )
        skus.append(response)
    return PublicProductDetail(
        **summary.model_dump(),
        skus=skus,
    )


def list_public_skus(
    session: Session,
    *,
    slug: str,
    query: str,
    category: str | None,
    tags: list[str],
    semantic: bool,
    include_facets: bool,
    page: int,
    page_size: int,
    locale: str | None = None,
) -> PublicSkuPage:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            locale,
            tenant=tenant,
            profile=profile,
        )
    )
    now = utcnow()
    wanted_tags = _normalize_tags(tags)
    all_categories = (
        repository.list_catalog_categories(session, tenant_id=tenant.id)
        if include_facets
        else []
    )

    if semantic and query.strip():
        try:
            rows = _vector_semantic_rows(
                session,
                tenant_id=tenant.id,
                query=query,
                now=now,
                category=category,
            )
        except EmbeddingProviderError:
            rows = _bounded_public_lexical_rows(
                session,
                tenant_id=tenant.id,
                query=query,
                now=now,
                category=category,
            )
        if wanted_tags:
            rows = [
                row
                for row in rows
                if wanted_tags.issubset(
                    {
                        str(tag).strip().casefold()
                        for tag in (row[0].tags or [])
                    }
                )
            ]
        total = len(rows)
        start = (page - 1) * page_size
        selected = rows[start : start + page_size]
    else:
        total = repository.count_public_catalog_rows(
            session,
            tenant_id=tenant.id,
            now=now,
            query=query,
            category=category,
            tags=wanted_tags,
        )
        selected = repository.list_public_catalog_page(
            session,
            tenant_id=tenant.id,
            now=now,
            query=query,
            category=category,
            tags=wanted_tags,
            page=page,
            page_size=page_size,
        )

    if include_facets:
        visible_category_ids = repository.list_public_catalog_category_ids(
            session,
            tenant_id=tenant.id,
            now=now,
            query="",
            category=None,
        )
    else:
        visible_category_ids = set()

    categories = _ordered_category_paths(
        visible_category_ids,
        all_categories=all_categories,
    )
    category_rows_by_id = {row.id: row for row in all_categories}
    category_colors_by_id = {
        row.id: (
            row.display_color
            if row.parent_id is None
            else category_rows_by_id.get(row.parent_id).display_color
            if category_rows_by_id.get(row.parent_id) is not None
            else None
        )
        for row in all_categories
    }
    images = repository.approved_image_map(
        session,
        tenant_id=tenant.id,
        product_ids={row[2].id for row in selected},
    )
    translator = _live_translation_provider(
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    translations = _live_sku_translation_map(
        selected,
        tenant_id=tenant.id,
        translator=translator,
        source_locale=source_locale,
        target_locale=requested_locale,
        additional_values=[
            segment.strip()
            for category_path in categories
            for segment in category_path.replace("／", "/").split("/")
            if segment.strip()
        ]
        if requested_locale != source_locale and include_facets
        else None,
    )
    category_labels = (
        _live_category_labels(
            categories,
            tenant_id=tenant.id,
            translator=translator,
            source_locale=source_locale,
            target_locale=requested_locale,
        )
        if requested_locale != source_locale and include_facets
        else {}
    )
    return PublicSkuPage(
        items=[
            _sku_response(
                row,
                image=images.get(row[2].id),
                slug=tenant.slug,
                category_color=(
                    category_colors_by_id.get(row[3].id)
                    if row[3] is not None
                    else None
                ),
                source_locale=source_locale,
                locale=requested_locale,
                translation=translations.get(row[1].id),
            )
            for row in selected
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        categories=categories,
        category_options=[
            PublicCategoryOption(
                value=category_path,
                label=category_labels.get(category_path, category_path),
            )
            for category_path in categories
        ],
        # Storefront tag chips were removed. Individual SKU tags remain in
        # each card and in semantic search, but the first page no longer scans
        # every public offer just to build an unused global facet.
        tags=[],
        source_locale=source_locale,
        locale=requested_locale,
        all_products_position=(
            _effective_all_products_position(
                profile.all_products_position,
                visible_category_ids=visible_category_ids,
                all_categories=all_categories,
            )
            if include_facets
            else 0
        ),
    )


def get_public_sku(
    session: Session,
    *,
    slug: str,
    sku_id: UUID,
    locale: str | None = None,
) -> PublicSkuResponse:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            locale,
            tenant=tenant,
            profile=profile,
        )
    )
    rows = repository.list_public_catalog_rows_by_sku_ids(
        session,
        tenant_id=tenant.id,
        sku_ids=[sku_id],
        now=utcnow(),
    )
    if not rows:
        raise ApplicationError(
            "PUBLIC_SKU_NOT_FOUND",
            "Public SKU was not found.",
            kind="not_found",
        )
    row = rows[0]
    categories = repository.list_catalog_categories(
        session, tenant_id=tenant.id
    )
    categories_by_id = {category.id: category for category in categories}
    category = row[3]
    root_category = (
        categories_by_id.get(category.parent_id)
        if category is not None and category.parent_id is not None
        else category
    )
    images = repository.approved_image_map(
        session,
        tenant_id=tenant.id,
        product_ids={row[2].id},
    )
    translator = _live_translation_provider(
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    translations = _live_sku_translation_map(
        [row],
        tenant_id=tenant.id,
        translator=translator,
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    return _sku_response(
        row,
        image=images.get(row[2].id),
        slug=tenant.slug,
        category_color=(
            root_category.display_color if root_category is not None else None
        ),
        source_locale=source_locale,
        locale=requested_locale,
        translation=translations.get(sku_id),
    )


def _item_response(row: PublicQuoteDraftItemRow) -> PublicQuoteDraftItemResponse:
    return PublicQuoteDraftItemResponse(
        id=row.id,
        sku_id=row.sku_id,
        position=row.position,
        quantity=row.quantity,
        sku_code_snapshot=row.sku_code_snapshot,
        name_snapshot=row.name_snapshot,
        description_snapshot=row.description_snapshot,
        specification_snapshot=row.specification_snapshot,
        option_values_snapshot=row.option_values_snapshot or {},
        category_snapshot=row.category_snapshot,
        tags_snapshot=row.tags_snapshot,
        image_url_snapshot=row.image_url_snapshot,
        unit_code_snapshot=row.unit_code_snapshot,
        currency_snapshot=row.currency_snapshot,
        unit_price_snapshot=row.unit_price_snapshot,
        line_total=row.line_total,
        product_version=row.product_version,
        sku_version=row.sku_version,
    )


def _quote_specification(option_values: dict[str, object]) -> str | None:
    parts: list[str] = []
    for key, value in option_values.items():
        label = str(key).strip()
        if not label or label.startswith("_") or value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            text = ", ".join(
                f"{nested_key}: {nested_value}"
                for nested_key, nested_value in value.items()
                if str(nested_value).strip()
            )
        else:
            text = str(value).strip()
        if text:
            parts.append(f"{label}: {text}")
    return "；".join(parts) or None


def _draft_response(
    draft: PublicQuoteDraftRow,
    items: list[PublicQuoteDraftItemRow],
    *,
    raw_token: str | None = None,
    token_expires_at: datetime | None = None,
) -> PublicQuoteDraftResponse:
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    document_base = f"{base}/api/quotes/{draft.id}" if base else f"/api/quotes/{draft.id}"
    return PublicQuoteDraftResponse(
        id=draft.id,
        tenant_id=draft.tenant_id,
        quote_number=draft.request_number,
        status=draft.status,
        customer_name=draft.customer_name,
        customer_company=draft.customer_company,
        customer_email=draft.customer_email,
        customer_phone=draft.customer_phone,
        notes=draft.notes,
        currency=draft.currency,
        subtotal=draft.subtotal_amount,
        total=draft.estimated_total,
        total_amount=draft.estimated_total,
        valid_until=draft.expires_at,
        created_at=draft.created_at,
        content_hash=draft.content_hash,
        disclaimer=PUBLIC_DRAFT_DISCLAIMER,
        disclaimer_version=draft.disclaimer_version,
        items=[_item_response(item) for item in items],
        download_token=raw_token,
        download_expires_at=token_expires_at,
        pdf_url=f"{document_base}/pdf" if raw_token else None,
        xlsx_url=f"{document_base}/xlsx" if raw_token else None,
    )


def create_public_quote_draft(
    session: Session,
    *,
    slug: str,
    request: PublicQuoteDraftCreate,
    submitted_by_membership_id: UUID | None = None,
    submitted_by_tenant_id: UUID | None = None,
    submitted_by_user_id: UUID | None = None,
) -> PublicQuoteDraftResponse:
    tenant, _profile = _resolve_store(session, slug=slug)
    if submitted_by_membership_id is not None:
        if (
            submitted_by_tenant_id != tenant.id
            or submitted_by_user_id is None
        ):
            raise ApplicationError(
                "PUBLIC_CUSTOMER_ACCOUNT_CONTEXT_INVALID",
                "Customer account context is invalid.",
                kind="forbidden",
            )
        set_request_context(
            session,
            organization_id=tenant.organization_id,
            tenant_id=tenant.id,
            user_id=submitted_by_user_id,
        )
    now = utcnow()
    draft_id = uuid4()
    sku_ids = [item.sku_id for item in request.items]
    rows = repository.list_public_catalog_rows_by_sku_ids(
        session,
        tenant_id=tenant.id,
        sku_ids=sku_ids,
        now=now,
    )
    row_by_sku = {row[1].id: row for row in rows}
    missing = [str(sku_id) for sku_id in sku_ids if sku_id not in row_by_sku]
    if missing:
        raise ApplicationError(
            "PUBLIC_SKU_NOT_FOUND",
            "One or more public SKUs were not found: " + ", ".join(missing),
        )
    currencies = {row[0].currency for row in rows}
    if len(currencies) != 1:
        raise ApplicationError(
            "PUBLIC_CART_MIXED_CURRENCY",
            "A draft cannot mix currencies; submit separate carts.",
        )
    currency = next(iter(currencies))
    images = repository.approved_image_map(
        session,
        tenant_id=tenant.id,
        product_ids={row[2].id for row in rows},
    )
    item_rows: list[PublicQuoteDraftItemRow] = []
    snapshot_items: list[dict[str, object]] = []
    subtotal = Decimal("0")
    for position, cart_item in enumerate(request.items, 1):
        offer, sku, product, category = row_by_sku[cart_item.sku_id]
        quantity = Decimal(cart_item.quantity)
        unit_price = _money(Decimal(offer.unit_price))
        line_total = _money(unit_price * quantity)
        subtotal += line_total
        tags = [str(tag).strip() for tag in (offer.tags or []) if str(tag).strip()]
        option_values = {
            str(key): value
            for key, value in (sku.option_values or {}).items()
            if str(key).strip() and not str(key).startswith("_")
        }
        specification = _quote_specification(option_values)
        image_url = _public_image_url(images.get(product.id), slug=tenant.slug)
        item_row = PublicQuoteDraftItemRow(
            tenant_id=tenant.id,
            quote_draft_id=draft_id,
            sku_id=sku.id,
            position=position,
            quantity=quantity,
            product_id_snapshot=product.id,
            product_version=product.current_version,
            sku_version=sku.version,
            sku_code_snapshot=sku.sku_code,
            name_snapshot=sku.name or product.name,
            description_snapshot=product.description,
            specification_snapshot=specification,
            option_values_snapshot=option_values,
            category_snapshot=_category_path(category) or None,
            tags_snapshot=list(dict.fromkeys(tags)),
            image_url_snapshot=image_url,
            minimum_order_quantity=Decimal("1"),
            unit_code_snapshot=product.default_unit or "piece",
            currency_snapshot=currency,
            unit_price_snapshot=unit_price,
            line_total=line_total,
        )
        item_rows.append(item_row)
        snapshot_items.append(
            {
                "position": position,
                "sku_id": str(sku.id),
                "product_id": str(product.id),
                "product_version": product.current_version,
                "sku_version": sku.version,
                "sku_code": sku.sku_code,
                "name": item_row.name_snapshot,
                "description": item_row.description_snapshot,
                "specification": specification,
                "option_values": option_values,
                "category": item_row.category_snapshot,
                "tags": item_row.tags_snapshot,
                "image_url": image_url,
                "quantity": str(quantity),
                "unit_code": item_row.unit_code_snapshot,
                "currency": currency,
                "unit_price": str(unit_price),
                "line_total": str(line_total),
            }
        )
    subtotal = _money(subtotal)
    expires_at = now + timedelta(
        days=_positive_int_environment("PUBLIC_QUOTE_DRAFT_VALID_DAYS", 7, maximum=90)
    )
    request_number = f"QD-{now:%Y%m%d}-{uuid4().hex[:8].upper()}"
    snapshot = {
        "document_type": "PUBLIC_QUOTE_DRAFT",
        "status": "PENDING_CONFIRMATION",
        "request_number": request_number,
        "tenant_id": str(tenant.id),
        "customer": {
            "name": request.customer_name,
            "company": request.customer_company,
            "email": request.customer_email,
            "phone": request.customer_phone,
        },
        "notes": request.notes,
        "privacy_notice": {
            "acknowledged": request.privacy_acknowledged,
            "version": PUBLIC_PRIVACY_NOTICE_VERSION,
            "acknowledged_at": now.isoformat(),
        },
        "currency": currency,
        "subtotal_amount": str(subtotal),
        "estimated_total": str(subtotal),
        "expires_at": expires_at.isoformat(),
        "disclaimer_version": PUBLIC_DRAFT_DISCLAIMER_VERSION,
        "items": snapshot_items,
    }
    content_hash = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    draft = PublicQuoteDraftRow(
        id=draft_id,
        tenant_id=tenant.id,
        request_number=request_number,
        status="PENDING_CONFIRMATION",
        submitted_by_membership_id=submitted_by_membership_id,
        customer_name=request.customer_name,
        customer_company=request.customer_company,
        customer_email=request.customer_email,
        customer_phone=request.customer_phone,
        notes=request.notes,
        currency=currency,
        subtotal_amount=subtotal,
        estimated_total=subtotal,
        expires_at=expires_at,
        snapshot=snapshot,
        content_hash=content_hash,
        disclaimer_version=PUBLIC_DRAFT_DISCLAIMER_VERSION,
    )
    raw_token = f"{tenant.id}{PUBLIC_TOKEN_SEPARATOR}{new_secret()}"
    token_expires_at = min(
        expires_at,
        now
        + timedelta(
            seconds=_positive_int_environment(
                "PUBLIC_QUOTE_DOWNLOAD_TTL_SECONDS", 86_400, maximum=30 * 86_400
            )
        ),
    )
    token_row = PublicQuoteDownloadTokenRow(
        tenant_id=tenant.id,
        quote_draft_id=draft_id,
        token_hash=hash_secret(raw_token),
        expires_at=token_expires_at,
        one_time=False,
    )
    repository.add_quote_draft(
        session, draft=draft, items=item_rows, token=token_row
    )
    if submitted_by_membership_id is not None:
        session.add(
            CustomerAccountAccessEventRow(
                tenant_id=tenant.id,
                membership_id=submitted_by_membership_id,
                event_type="ORDER_SUBMITTED",
                occurred_at=now,
            )
        )
    response = _draft_response(
        draft,
        item_rows,
        raw_token=raw_token,
        token_expires_at=token_expires_at,
    )
    session.commit()
    return response


def _tenant_id_from_download_token(raw_token: str) -> UUID:
    prefix, separator, secret = raw_token.partition(PUBLIC_TOKEN_SEPARATOR)
    if not separator or not secret:
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND", "Download was not found.", kind="not_found"
        )
    try:
        return UUID(prefix)
    except ValueError as exc:
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND", "Download was not found.", kind="not_found"
        ) from exc


def get_quote_document(
    session: Session, *, quote_draft_id: UUID, raw_token: str
) -> PublicQuoteDocument:
    tenant_id = _tenant_id_from_download_token(raw_token)
    profile = repository.find_published_profile_by_tenant(
        session, tenant_id=tenant_id
    )
    if profile is None:
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND", "Download was not found.", kind="not_found"
        )
    set_public_tenant_context(session, tenant_id=tenant_id)
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id, slug=profile.slug)
    if tenant is None:
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND", "Download was not found.", kind="not_found"
        )
    token = repository.get_download_token(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        token_hash=hash_secret(raw_token),
    )
    if token is None or token.revoked_at is not None:
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND", "Download was not found.", kind="not_found"
        )
    if _as_utc(token.expires_at) <= utcnow():
        raise ApplicationError(
            "DOWNLOAD_EXPIRED", "The download link has expired.", kind="expired"
        )
    draft = repository.get_quote_draft(
        session, tenant_id=tenant_id, quote_draft_id=quote_draft_id
    )
    if draft is None or draft.status != "PENDING_CONFIRMATION":
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND", "Download was not found.", kind="not_found"
        )
    items = repository.list_quote_draft_items(
        session, tenant_id=tenant_id, quote_draft_id=quote_draft_id
    )
    return PublicQuoteDocument(
        tenant_name=tenant.name,
        contact_email=profile.contact_email,
        contact_phone=profile.contact_phone,
        quote=_draft_response(draft, items),
        excel_template=quote_template_use_cases.default_render_spec(
            session,
            tenant_id=tenant_id,
        ),
    )


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED", f"Permission is required: {code}", kind="forbidden"
        )


def list_tenant_quote_drafts(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    limit: int,
) -> list[PublicQuoteDraftSummary]:
    _require(permissions, "quotation.view")
    return [
        PublicQuoteDraftSummary(
            id=row.id,
            quote_number=row.request_number,
            status=row.status,
            customer_name=row.customer_name,
            customer_company=row.customer_company,
            currency=row.currency,
            total_amount=row.estimated_total,
            valid_until=row.expires_at,
            created_at=row.created_at,
        )
        for row in repository.list_quote_drafts(
            session, tenant_id=tenant_id, limit=limit
        )
    ]


def get_tenant_quote_draft(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
) -> PublicQuoteDraftResponse:
    _require(permissions, "quotation.view")
    draft = repository.get_quote_draft(
        session, tenant_id=tenant_id, quote_draft_id=quote_draft_id
    )
    if draft is None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    items = repository.list_quote_draft_items(
        session, tenant_id=tenant_id, quote_draft_id=quote_draft_id
    )
    return _draft_response(draft, items)


def get_tenant_quote_document(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
) -> PublicQuoteDocument:
    _require(permissions, "quotation.view")
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id)
    draft = repository.get_quote_draft(
        session, tenant_id=tenant_id, quote_draft_id=quote_draft_id
    )
    if tenant is None or draft is None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    profile = repository.find_profile_by_tenant(session, tenant_id=tenant_id)
    items = repository.list_quote_draft_items(
        session, tenant_id=tenant_id, quote_draft_id=quote_draft_id
    )
    return PublicQuoteDocument(
        tenant_name=tenant.name,
        contact_email=profile.contact_email if profile else None,
        contact_phone=profile.contact_phone if profile else None,
        quote=_draft_response(draft, items),
        excel_template=quote_template_use_cases.default_render_spec(
            session,
            tenant_id=tenant_id,
        ),
    )
