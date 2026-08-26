from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..database import set_public_tenant_context, set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import CustomerAccountAccessEventRow, MembershipRow
from ..knowledge_embedding_schemas import DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS
from ..model_mixins import utcnow
from ..public_catalog_models import (
    PublicQuoteDownloadTokenRow,
    PublicQuoteDraftItemRow,
    PublicQuoteDraftRow,
    StorefrontOrderRecordRow,
)
from ..public_catalog_schemas import (
    PUBLIC_DRAFT_DISCLAIMER,
    PUBLIC_DRAFT_DISCLAIMER_VERSION,
    PUBLIC_PRIVACY_NOTICE_VERSION,
    PublicQuoteDocument,
    PublicQuoteDraftCreate,
    PublicQuoteDraftCurrencyConversion,
    PublicQuoteDraftItemPatch,
    PublicQuoteDraftItemResponse,
    PublicQuoteDraftItemPriceUpdate,
    PublicQuoteDraftItemsUpdate,
    PublicQuoteDraftPriceAdjustment,
    PublicQuoteDraftResponse,
    PublicQuoteDraftSettingsUpdate,
    PublicQuoteDraftStatusUpdate,
    PublicQuoteDraftSummary,
    StorefrontOrderCurrencyStatistics,
    StorefrontOrderPeriodStatistics,
    StorefrontOrderStatistics,
    PublicCategoryOption,
    PublicExchangeRateResponse,
    PublicImageSearchResponse,
    PublicImageSearchResult,
    PublicProductDetail,
    PublicProductPage,
    PublicProductSummary,
    PublicSkuPage,
    PublicSkuResponse,
    PublicStoreResponse,
)
from ..repositories import public_catalog_repository as repository
from ..repositories import catalog_translation_repository
from ..repositories import quote_template_repository
from ..services.catalog_translation import (
    CatalogTranslationResult,
    catalog_translation_source,
)
from ..services.catalog_language_packages import (
    catalog_product_package_source_hash,
    catalog_sku_package_source_hash,
    load_language_pack_payload,
)
from ..services.language_package_storage import configured_language_package_storage
from ..services.public_catalog_privacy import (
    is_private_sku_option_key,
    public_sku_option_values,
    public_specification,
)
from ..services.auth.tokens import hash_secret, new_secret
from ..services.auth.service import AuthError, session_from_access_token
from ..services.embedding import EmbeddingProviderError
from ..services.hybrid_search import (
    _retrieval_tokens,
    _score_overlap,
    hybrid_product_search,
)
from ..services.rbac import list_permissions
from ..services.storefront_branding import storefront_logo_url
from ..services.translation import (
    TranslationProvider,
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)
from ..services.translation_memory import translate_values_with_memory
from ..services.subaccount_pricing import (
    effective_subaccount_price,
    subaccount_price_rules,
)
from ..services.platform_usage import increment_image_search
from ..services.translation_configuration import (
    resolved_catalog_translator,
    translation_provider_is_configured,
)
from ..services.world_market import (
    get_dashboard_market_snapshot,
    get_exchange_rate_snapshot,
)
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


def _public_ai_search_questions(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        question = str(item).strip()[:200]
        key = question.casefold()
        if not question or key in seen:
            continue
        seen.add(key)
        normalized.append(question)
    return normalized[:5] or list(DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS)


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
    member_context = optional_customer_subaccount_membership(
        identity_session,
        access_token=access_token,
    )
    if member_context is None:
        return None
    membership, user = member_context
    if "customer_portal.order_create" not in list_permissions(
        identity_session, tenant_id=membership.tenant_id, user_id=user.id
    ):
        raise ApplicationError(
            "CUSTOMER_ORDER_CREATE_DENIED",
            "This subaccount is not allowed to submit quotations.",
            kind="forbidden",
        )
    return CustomerQuoteSubmitter(
        membership_id=membership.id,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    )


def optional_customer_subaccount_membership(
    identity_session: Session,
    *,
    access_token: str | None,
) -> tuple[MembershipRow, object] | None:
    """Resolve a child-account bearer token for public catalog pricing.

    Public visitors remain anonymous.  A valid child-account session enriches
    the same storefront response with reseller pricing without exposing the
    parent account's internal APIs or supplier data.
    """

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
    if "customer_portal.access" not in list_permissions(
        identity_session,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    ):
        return None
    return membership, user


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


def _catalog_row_updated_at(row: object) -> datetime:
    values = [
        _as_utc(value)
        for item in row
        if item is not None
        if (value := getattr(item, "updated_at", None)) is not None
    ]
    return max(values, default=datetime(1970, 1, 1, tzinfo=UTC))


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
        media_url = f"{base}/{quote(object_key.lstrip('/'), safe='/')}"
        cache_key = str(getattr(image, "sha256", "") or "").strip()[:16]
        if cache_key:
            return f"{media_url}?v={quote(cache_key, safe='')}"
        return media_url
    media_url = f"/api/store/{quote(slug, safe='')}/media/{image.id}"
    # Product image replacement reuses the database row id.  Version the
    # proxy URL by content so the browser/CDN fetches the new bytes instead
    # of serving a cached copy of the previous image.
    cache_key = str(getattr(image, "sha256", "") or "").strip()[:16]
    if cache_key:
        return f"{media_url}?v={quote(cache_key, safe='')}"
    return media_url


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
    session: Session,
    tenant: object,
    profile: object,
) -> list[str]:
    del session
    source_locale = _normalized_locale(getattr(tenant, "default_locale", None))
    # Visibility is a merchant setting, not a translation-runtime capability.
    # A selected language must remain available even before its package is
    # published or when live translation is temporarily unavailable; catalog
    # responses already mark untranslated content as FALLBACK and return the
    # source text. Hiding it here made the frontend remove the language switch
    # despite the merchant having explicitly enabled multiple languages.
    return effective_storefront_locales(
        getattr(profile, "storefront_locales", None),
        source_locale=source_locale,
    )


def _requested_storefront_locale(
    session: Session,
    locale: str | None,
    *,
    tenant: object,
    profile: object,
) -> tuple[str, str, list[str]]:
    source_locale = _normalized_locale(getattr(tenant, "default_locale", None))
    available_locales = _available_storefront_locales(session, tenant, profile)
    default_locale = _normalized_locale(
        getattr(profile, "storefront_default_locale", None),
        default=source_locale,
    )
    if default_locale not in available_locales:
        default_locale = source_locale
    requested_locale = _normalized_locale(locale, default=default_locale)
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


def _ordered_visible_category_rows(
    visible_category_ids: set[UUID], *, all_categories: list[object]
) -> list[object]:
    categories_by_id = {
        getattr(category, "id"): category
        for category in all_categories
        if getattr(category, "id", None) is not None
    }
    included_ids: set[UUID] = set()
    for category_id in visible_category_ids:
        category = categories_by_id.get(category_id)
        if category is None or not _category_path(category):
            continue
        included_ids.add(category_id)
        parent_id = getattr(category, "parent_id", None)
        if parent_id in categories_by_id:
            included_ids.add(parent_id)

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

    return sorted(
        (categories_by_id[category_id] for category_id in included_ids),
        key=sort_key,
    )


def _public_category_options(
    session: Session,
    *,
    tenant_id: UUID,
    slug: str,
    visible_category_ids: set[UUID],
    all_categories: list[object],
    labels: dict[str, str],
) -> list[PublicCategoryOption]:
    rows = _ordered_visible_category_rows(
        visible_category_ids,
        all_categories=all_categories,
    )
    cover_product_ids = {
        getattr(row, "cover_product_id", None)
        for row in rows
        if str(getattr(row, "cover_source", "NONE") or "NONE").upper()
        == "PRODUCT"
        and getattr(row, "cover_product_id", None) is not None
    }
    cover_images = repository.approved_image_map(
        session,
        tenant_id=tenant_id,
        product_ids=cover_product_ids,
    )
    result: list[PublicCategoryOption] = []
    for row in rows:
        path = _category_path(row)
        cover_source = str(getattr(row, "cover_source", "NONE") or "NONE").upper()
        cover_url = None
        if cover_source == "UPLOAD" and str(
            getattr(row, "cover_object_key", "") or ""
        ).strip():
            object_key = str(getattr(row, "cover_object_key", "") or "").strip()
            media_base_url = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
            cover_url = (
                f"{media_base_url}/{quote(object_key.lstrip('/'), safe='/')}"
                if media_base_url
                else (
                    f"/api/store/{quote(slug, safe='')}/categories/{row.id}/cover"
                    f"?v={getattr(row, 'version', 1)}"
                )
            )
        elif cover_source == "PRODUCT":
            cover_url = _public_image_url(
                cover_images.get(getattr(row, "cover_product_id", None)),
                slug=slug,
            )
        result.append(
            PublicCategoryOption(
                id=row.id,
                parent_id=getattr(row, "parent_id", None),
                value=path,
                label=labels.get(path, path),
                cover_image_url=cover_url,
            )
        )
    return result


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


def get_public_store_logo(session: Session, *, slug: str) -> tuple[bytes, str]:
    _tenant, profile = _resolve_store(session, slug=slug)
    object_key = str(profile.logo_object_key or "").strip()
    if not object_key:
        raise ApplicationError(
            "PUBLIC_LOGO_NOT_FOUND", "Store logo was not found.", kind="not_found"
        )
    try:
        with get_object_storage().materialize(object_key) as path:
            return path.read_bytes(), "image/webp"
    except Exception as exc:
        raise ApplicationError(
            "PUBLIC_LOGO_NOT_FOUND", "Store logo was not found.", kind="not_found"
        ) from exc


def get_public_category_cover(
    session: Session,
    *,
    slug: str,
    category_id: UUID,
) -> tuple[bytes, str]:
    tenant, _profile = _resolve_store(session, slug=slug)
    category = repository.get_catalog_category(
        session,
        tenant_id=tenant.id,
        category_id=category_id,
    )
    object_key = str(getattr(category, "cover_object_key", "") or "").strip()
    if category is None or category.status != "ACTIVE" or not object_key:
        raise ApplicationError(
            "PUBLIC_CATEGORY_COVER_NOT_FOUND",
            "Category cover was not found.",
            kind="not_found",
        )
    try:
        with get_object_storage().materialize(object_key) as path:
            return path.read_bytes(), "image/webp"
    except Exception as exc:
        raise ApplicationError(
            "PUBLIC_CATEGORY_COVER_NOT_FOUND",
            "Category cover was not found.",
            kind="not_found",
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
            session,
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
        logo_url=storefront_logo_url(profile),
        contact_email=profile.contact_email,
        contact_phone=profile.contact_phone,
        default_currency=tenant.default_currency,
        locale=requested_locale,
        source_locale=source_locale,
        available_locales=available_locales,
        all_products_position=max(0, int(profile.all_products_position or 0)),
        hot_products_enabled=bool(profile.hot_products_enabled),
        category_showcase_enabled=bool(profile.category_showcase_enabled),
        ai_search_questions=_public_ai_search_questions(
            getattr(profile, "ai_search_questions", None),
        ),
        announcements=announcement_use_cases.public_announcements(
            session,
            tenant_id=tenant.id,
        ),
        support_widget=support_use_cases.public_widget(session, profile),
    )


def get_public_exchange_rates(
    session: Session,
    *,
    slug: str,
) -> PublicExchangeRateResponse:
    """Expose shared reference FX data only for a published storefront."""

    _resolve_store(session, slug=slug)
    market = get_exchange_rate_snapshot()
    return PublicExchangeRateResponse(
        observed_at=market.observed_at,
        exchange_rates=[item.model_dump() for item in market.exchange_rates],
        rate_date=market.rate_date,
        rate_source=market.rate_source,
    )


def _sku_response(
    row: object,
    *,
    image: object | None,
    slug: str,
    category_color: str | None,
    source_locale: str,
    locale: str,
    display_currency: str,
    translation: object | None = None,
    product_translation: PublicProductTranslation | None = None,
    pricing_markup_percent: Decimal = Decimal("0"),
    pricing_overrides: dict[UUID, object] | None = None,
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
    source_specification = str(
        (sku.option_values or {}).get("规格名称") or ""
    ).strip() or None
    translated_specification = (
        str(getattr(translation, "specification", "") or "").strip() or None
        if translated
        else None
    )
    localized_specification = (
        translated_specification
        or (
            product_translation.specifications.get(
                source_specification,
                source_specification,
            )
            if product_translation is not None and source_specification
            else source_specification
        )
        or None
    )
    localized_options = _localized_public_option_values(
        dict(sku.option_values or {}),
        translation=(
            product_translation
            if locale != source_locale
            else None
        ),
    )
    if localized_specification:
        localized_options["规格名称"] = localized_specification
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
        price=effective_subaccount_price(
            _money(Decimal(offer.unit_price)),
            markup_percent=pricing_markup_percent,
            override=(pricing_overrides or {}).get(product.id),
        ),
        currency=display_currency,
        unit_code=product.default_unit or "piece",
        image_url=_public_image_url(image, slug=slug),
        product_version=product.current_version,
        sku_version=sku.version,
        source_updated_at=_catalog_row_updated_at(row),
        translation_source_hash=catalog_sku_package_source_hash(row),
        specification=localized_specification,
        option_values=localized_options,
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
    session: Session,
    *,
    source_locale: str,
    target_locale: str,
) -> TranslationProvider | None:
    if target_locale == source_locale:
        return None
    try:
        return resolved_catalog_translator(
            session,
            environment_factory=configured_catalog_translator,
        )
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
    translated with an English source language. Providers without native
    mixed-language support receive a cached English-to-target repair pass;
    capable LLM providers translate mixed text once to avoid duplicate work.
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

    requires_english_repair = not bool(
        getattr(translator, "translates_mixed_language_text", False)
    )
    if target_locale not in {"en", "en-US"} and requires_english_repair:
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
            if (
                normalized
                and not is_private_sku_option_key(normalized)
                and normalized not in explicit
            ):
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
                and not is_private_sku_option_key(normalized)
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
    # SKU notes are operator-only data.  Sanitize before applying translation
    # so the source locale and every translated storefront use the same rule.
    localized = public_sku_option_values(option_values)
    if translation is None or not translation.option_labels:
        return localized

    marker = localized.get(_PUBLIC_OPTION_INTERNAL_KEY)
    localized_marker = dict(marker) if isinstance(marker, dict) else None
    marker_keys = (
        [
            str(key).strip()
            for key in localized_marker.get("variant_option_keys", [])
            if (
                isinstance(key, str)
                and str(key).strip()
                and not is_private_sku_option_key(key)
            )
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
    specifications = [
        str((row[1].option_values or {}).get("规格名称") or "").strip()
        for row in rows
    ]
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
    metadata_candidates.extend(
        specification
        for specification in specifications
        if specification
    )
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
                specifications[index],
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
            specification=(
                translated_values.get(
                    specifications[index],
                    specifications[index],
                )
                if specifications[index]
                else None
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
    sku_translation_sink: dict[UUID, CatalogTranslationResult] | None = None,
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
        sku_sources = [
            catalog_translation_source(row)
            for row in rows
        ] if sku_translation_sink is not None else []
        translation_values.extend(
            source.name
            for source in sku_sources
            if _is_translatable_catalog_text(source.name)
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
                "rows": rows,
                "sku_sources": sku_sources,
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
        rows = source["rows"]
        sku_sources = source["sku_sources"]
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
        localized_description = (
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
        )
        localized_category = (
            "/".join(
                translated_values.get(segment, segment)
                for segment in category_segments
            )
            or None
        )
        results[source["product_id"]] = PublicProductTranslation(
            name=translated_values.get(name, name),
            description=localized_description,
            category=localized_category,
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
        if sku_translation_sink is not None:
            for row, sku_source in zip(rows, sku_sources, strict=True):
                sku_category_segments = [
                    segment.strip()
                    for segment in (sku_source.category or "")
                    .replace("／", "/")
                    .split("/")
                    if segment.strip()
                ]
                localized_sku_tags = tuple(
                    translated_values.get(tag, tag)
                    for tag in sku_source.tags
                )
                source_specification = str(
                    (row[1].option_values or {}).get("规格名称") or ""
                ).strip()
                display_tag_index = next(
                    (
                        index
                        for index, tag in enumerate(sku_source.tags)
                        if sku_source.display_tag
                        and tag.casefold() == sku_source.display_tag.casefold()
                    ),
                    None,
                )
                if sku_source.sku_id in sku_translation_sink:
                    continue
                sku_translation_sink[sku_source.sku_id] = CatalogTranslationResult(
                    sku_id=sku_source.sku_id,
                    source_hash=sku_source.source_hash,
                    name=translated_values.get(sku_source.name, sku_source.name),
                    description=localized_description,
                    category=(
                        "/".join(
                            translated_values.get(segment, segment)
                            for segment in sku_category_segments
                        )
                        or None
                    ),
                    tags=localized_sku_tags,
                    display_tag=(
                        localized_sku_tags[display_tag_index]
                        if display_tag_index is not None
                        else localized_sku_tags[0]
                        if localized_sku_tags
                        else None
                    ),
                    specification=(
                        translated_values.get(
                            source_specification,
                            source_specification,
                        )
                        if source_specification
                        else None
                    ),
                    complete=all(
                        value.strip() in complete_values
                        for value in (
                            sku_source.name,
                            *sku_category_segments,
                            *sku_source.tags,
                            source_specification,
                        )
                        if _is_translatable_catalog_text(value)
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
    display_currency: str,
    translation: PublicProductTranslation | None,
    pricing_markup_percent: Decimal = Decimal("0"),
    pricing_overrides: dict[UUID, object] | None = None,
) -> PublicProductSummary:
    _offer, first_sku, product, category = rows[0]
    tags = _product_group_tags(rows)
    display_tag = _product_group_display_tag(rows, tags=tags)
    translated = translation is not None and locale != source_locale
    prices = [
        effective_subaccount_price(
            _money(Decimal(row[0].unit_price)),
            markup_percent=pricing_markup_percent,
            override=(pricing_overrides or {}).get(product.id),
        )
        for row in rows
    ]
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
        currency=display_currency,
        unit_code=product.default_unit or "piece",
        image_url=_public_image_url(image, slug=slug),
        sku_count=len({row[1].id for row in rows}),
        product_version=product.current_version,
        source_updated_at=max(_catalog_row_updated_at(row) for row in rows),
        translation_source_hash=catalog_product_package_source_hash(rows),
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
        source_sku_code = str(sku.source_sku_code or "").casefold()
        sku_name = str(sku.name or "").casefold()
        product_name = str(product.name).casefold()
        description = str(product.description or "").casefold()
        category_name = _category_path(row_category).casefold()
        tag_values = [str(tag).casefold() for tag in (offer.tags or [])]
        fields = [
            sku_code,
            source_sku_code,
            sku_name,
            product_name,
            description,
            category_name,
            *tag_values,
        ]
        coverage = _score_overlap(query_tokens, " ".join(fields))
        score = coverage
        if sku_code == normalized_query:
            score += 2.0
        elif source_sku_code == normalized_query:
            score += 2.0
        elif normalized_query in sku_code:
            score += 0.8
        elif normalized_query in source_sku_code:
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
    # A copied title or SKU is a deterministic catalog lookup, not a semantic
    # question.  Resolve it before the bounded n-gram pool so a large catalog
    # cannot evict the exact row before in-memory relevance scoring begins.
    exact_rows = repository.list_public_catalog_exact_candidates(
        session,
        tenant_id=tenant_id,
        now=now,
        query=query,
        category=category,
        limit=_positive_int_environment(
            "PUBLIC_EXACT_SEARCH_RESULT_LIMIT",
            200,
            maximum=500,
        ),
    )
    if exact_rows:
        return _lexical_semantic_rows(exact_rows, query=query)

    # Other text matches are still sourced directly from the published catalog,
    # so a product remains searchable when its knowledge index is missing or
    # stale. Semantic retrieval only runs when catalog text cannot answer.
    lexical_rows = _bounded_public_lexical_rows(
        session,
        tenant_id=tenant_id,
        query=query,
        now=now,
        category=category,
    )
    if lexical_rows:
        return lexical_rows
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
        return lexical_rows
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
    share_token: str | None = None,
    subaccount_membership_id: UUID | None = None,
    ranked_product_ids: list[UUID] | None = None,
) -> PublicProductPage:
    tenant, profile = _resolve_store(session, slug=slug)
    shared_product_ids: set[UUID] | None = None
    if share_token:
        from .catalog_shares import resolve_share_constraint

        share_constraint = resolve_share_constraint(
            session, tenant_id=tenant.id, token=share_token
        )
        if share_constraint.target_type == "CATEGORY":
            category = share_constraint.category_path
        else:
            shared_product_ids = set(share_constraint.product_ids)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            session,
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
        and not share_token
        and ranked_product_ids is None
    )
    all_categories = (
        repository.list_catalog_categories(session, tenant_id=tenant.id)
        if include_facets
        else []
    )

    if ranked_product_ids is not None:
        matching_product_ids = list(dict.fromkeys(ranked_product_ids))
        if shared_product_ids is not None:
            matching_product_ids = [
                product_id
                for product_id in matching_product_ids
                if product_id in shared_product_ids
            ]
        total = len(matching_product_ids)
        start = (page - 1) * page_size
        selected_product_ids = matching_product_ids[start : start + page_size]
    elif semantic and query.strip():
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
        if shared_product_ids is not None:
            matching_product_ids = [
                product_id
                for product_id in matching_product_ids
                if product_id in shared_product_ids
            ]
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
            product_ids=shared_product_ids,
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
            product_ids=shared_product_ids,
            hot=hot_sort_applied,
        )

    selected_rows = repository.list_public_catalog_rows_by_product_ids(
        session,
        tenant_id=tenant.id,
        product_ids=selected_product_ids,
        now=now,
        category=category,
    )
    pricing_markup_percent, pricing_overrides, _hidden_product_ids = subaccount_price_rules(
        session,
        tenant_id=tenant.id,
        membership_id=subaccount_membership_id,
        product_ids=set(selected_product_ids),
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
            product_ids=shared_product_ids,
        )
    else:
        visible_category_ids = set()
    categories = _ordered_category_paths(
        visible_category_ids,
        all_categories=all_categories,
    )
    category_option_paths = [
        _category_path(row)
        for row in _ordered_visible_category_rows(
            visible_category_ids,
            all_categories=all_categories,
        )
    ]
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
    _sku_translations, translations = _quote_translation_maps(
        session,
        tenant_id=tenant.id,
        rows=selected_rows,
        source_locale=source_locale,
        target_locale=requested_locale,
        include_product_translations=True,
        include_sku_options=False,
    )
    translator = _live_translation_provider(
        session,
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    category_labels = (
        _live_category_labels(
            category_option_paths,
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
                display_currency=tenant.default_currency.upper(),
                translation=translations.get(rows[0][2].id),
                pricing_markup_percent=pricing_markup_percent,
                pricing_overrides=pricing_overrides,
            )
            for rows in groups
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        categories=categories,
        category_options=_public_category_options(
            session,
            tenant_id=tenant.id,
            slug=tenant.slug,
            visible_category_ids=visible_category_ids,
            all_categories=all_categories,
            labels=category_labels,
        ),
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
        category_showcase_enabled=bool(profile.category_showcase_enabled),
        hot_sort_applied=hot_sort_applied,
    )


def search_public_products_by_image(
    session: Session,
    *,
    slug: str,
    content: bytes,
    declared_content_type: str,
    limit: int,
    locale: str | None = None,
    share_token: str | None = None,
    subaccount_membership_id: UUID | None = None,
    timings: dict[str, float] | None = None,
) -> PublicImageSearchResponse:
    """Run private-R2-backed visual search against published catalog offers."""

    started = time.perf_counter()
    tenant, _profile = _resolve_store(session, slug=slug)
    if timings is not None:
        timings["store"] = (time.perf_counter() - started) * 1000
    allowed_product_ids: set[UUID] | None = None
    shared_category: str | None = None
    if share_token:
        from .catalog_shares import resolve_share_constraint

        share_constraint = resolve_share_constraint(
            session,
            tenant_id=tenant.id,
            token=share_token,
        )
        if share_constraint.target_type == "PRODUCTS":
            allowed_product_ids = set(share_constraint.product_ids)
        else:
            shared_category = share_constraint.category_path

    from .image_intelligence import search_public_image_matches

    matches = search_public_image_matches(
        session,
        tenant_id=tenant.id,
        declared_content_type=declared_content_type,
        content=content,
        limit=limit,
        allowed_product_ids=allowed_product_ids,
        category=shared_category,
        timings=timings,
    )
    started = time.perf_counter()
    page = list_public_products(
        session,
        slug=slug,
        query="",
        category=None,
        tags=[],
        semantic=False,
        include_facets=False,
        page=1,
        page_size=max(1, limit),
        locale=locale,
        share_token=share_token,
        subaccount_membership_id=subaccount_membership_id,
        ranked_product_ids=[match.product_id for match in matches],
    )
    if timings is not None:
        timings["catalog"] = (time.perf_counter() - started) * 1000
    products_by_id = {product.id: product for product in page.items}
    results = [
        PublicImageSearchResult(
            product=products_by_id[match.product_id],
            matched_image_id=match.product_image_id,
            similarity=match.similarity,
            match_percent=match.match_percent,
            confidence=match.confidence,
        )
        for match in matches
        if match.product_id in products_by_id
    ]
    # Public image searches do not create an ImageSearchRow, so keep a small
    # daily counter for the platform usage dashboard instead.
    increment_image_search(session, tenant_id=tenant.id)
    session.commit()
    return PublicImageSearchResponse(
        id=uuid4(),
        status="COMPLETED" if results else "INDEX_EMPTY",
        results=results,
        warnings=(
            ["匹配度用于视觉相似筛选，商品规格和价格请以详情页为准。"]
            if results
            else ["当前店铺还没有可搜索的图片向量，请联系商家更新图片索引。"]
        ),
    )


def get_public_product(
    session: Session,
    *,
    slug: str,
    product_id: UUID,
    locale: str | None = None,
    share_token: str | None = None,
    subaccount_membership_id: UUID | None = None,
) -> PublicProductDetail:
    tenant, profile = _resolve_store(session, slug=slug)
    shared_category: str | None = None
    if share_token:
        from .catalog_shares import resolve_share_constraint

        share_constraint = resolve_share_constraint(
            session, tenant_id=tenant.id, token=share_token
        )
        if (
            share_constraint.target_type == "PRODUCTS"
            and product_id not in set(share_constraint.product_ids)
        ):
            raise ApplicationError(
                "PUBLIC_PRODUCT_NOT_FOUND",
                "Public product was not found.",
                kind="not_found",
            )
        if share_constraint.target_type == "CATEGORY":
            shared_category = share_constraint.category_path
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            session,
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
        category=shared_category,
    )
    if not rows:
        raise ApplicationError(
            "PUBLIC_PRODUCT_NOT_FOUND",
            "Public product was not found.",
            kind="not_found",
        )
    pricing_markup_percent, pricing_overrides, hidden_product_ids = subaccount_price_rules(
        session,
        tenant_id=tenant.id,
        membership_id=subaccount_membership_id,
        product_ids={product_id},
    )
    if product_id in hidden_product_ids:
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
    images = repository.approved_images_for_product(
        session,
        tenant_id=tenant.id,
        product_id=product_id,
    )
    image = images[0] if images else None
    sku_translations, product_translations = _quote_translation_maps(
        session,
        tenant_id=tenant.id,
        rows=rows,
        source_locale=source_locale,
        target_locale=requested_locale,
        include_product_translations=True,
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
        display_currency=tenant.default_currency.upper(),
        translation=product_translation,
        pricing_markup_percent=pricing_markup_percent,
        pricing_overrides=pricing_overrides,
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
            display_currency=tenant.default_currency.upper(),
            translation=sku_translations.get(row[1].id),
            product_translation=product_translation,
            pricing_markup_percent=pricing_markup_percent,
            pricing_overrides=pricing_overrides,
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
        sku_translation = sku_translations.get(row[1].id)
        localized_sku_name = (
            getattr(sku_translation, "name", None) or summary.name
        )
        should_append_specification = bool(
            specification
            and not (
                localized_sku_name.strip().casefold()
                == specification.casefold()
                or any(
                    localized_sku_name.strip().casefold().endswith(suffix)
                    for suffix in (
                        f" {specification.casefold()}",
                        f"·{specification.casefold()}",
                        f"· {specification.casefold()}",
                        f"/{specification.casefold()}",
                        f"-{specification.casefold()}",
                        f"_{specification.casefold()}",
                    )
                )
            )
        )
        response = response.model_copy(
            update={
                "name": (
                    f"{localized_sku_name} · {specification}"
                    if should_append_specification
                    else localized_sku_name
                ),
                "description": (
                    getattr(sku_translation, "description", None)
                    if sku_translation is not None
                    else summary.description
                ),
                "category_label": (
                    getattr(sku_translation, "category", None)
                    or summary.category_label
                ),
                "tags": (
                    list(getattr(sku_translation, "tags", ()) or ())
                    if sku_translation is not None
                    else localized_sku_tags
                ),
                "display_tag": (
                    getattr(sku_translation, "display_tag", None)
                    or localized_display_tag
                ),
                "specification": specification,
                "option_values": localized_option_values,
                "locale": requested_locale,
                "translation_status": response.translation_status,
            }
        )
        skus.append(response)
    return PublicProductDetail(
        **summary.model_dump(),
        image_urls=[
            image_url
            for image_row in images
            if (image_url := _public_image_url(image_row, slug=tenant.slug))
        ],
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
    subaccount_membership_id: UUID | None = None,
) -> PublicSkuPage:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            session,
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
    category_option_paths = [
        _category_path(row)
        for row in _ordered_visible_category_rows(
            visible_category_ids,
            all_categories=all_categories,
        )
    ]
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
    pricing_markup_percent, pricing_overrides, hidden_product_ids = subaccount_price_rules(
        session,
        tenant_id=tenant.id,
        membership_id=subaccount_membership_id,
        product_ids={row[2].id for row in selected},
    )
    selected = [row for row in selected if row[2].id not in hidden_product_ids]
    translations, product_translations = _quote_translation_maps(
        session,
        tenant_id=tenant.id,
        rows=selected,
        source_locale=source_locale,
        target_locale=requested_locale,
        include_product_translations=True,
        include_sku_options=True,
    )
    translator = _live_translation_provider(
        session,
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    category_labels = (
        _live_category_labels(
            category_option_paths,
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
                display_currency=tenant.default_currency.upper(),
                translation=translations.get(row[1].id),
                product_translation=product_translations.get(row[2].id),
                pricing_markup_percent=pricing_markup_percent,
                pricing_overrides=pricing_overrides,
            )
            for row in selected
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        categories=categories,
        category_options=_public_category_options(
            session,
            tenant_id=tenant.id,
            slug=tenant.slug,
            visible_category_ids=visible_category_ids,
            all_categories=all_categories,
            labels=category_labels,
        ),
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
        category_showcase_enabled=bool(profile.category_showcase_enabled),
    )


def get_public_sku(
    session: Session,
    *,
    slug: str,
    sku_id: UUID,
    locale: str | None = None,
    share_token: str | None = None,
    subaccount_membership_id: UUID | None = None,
) -> PublicSkuResponse:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            session,
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
    pricing_markup_percent, pricing_overrides, hidden_product_ids = subaccount_price_rules(
        session,
        tenant_id=tenant.id,
        membership_id=subaccount_membership_id,
        product_ids={row[2].id},
    )
    if row[2].id in hidden_product_ids:
        raise ApplicationError(
            "PUBLIC_SKU_NOT_FOUND",
            "Public SKU was not found.",
            kind="not_found",
        )
    if share_token:
        from .catalog_shares import resolve_share_constraint

        share_constraint = resolve_share_constraint(
            session, tenant_id=tenant.id, token=share_token
        )
        allowed = row[2].id in set(share_constraint.product_ids)
        if share_constraint.target_type == "CATEGORY":
            allowed_rows = repository.list_public_catalog_rows_by_product_ids(
                session,
                tenant_id=tenant.id,
                product_ids=[row[2].id],
                now=utcnow(),
                category=share_constraint.category_path,
            )
            allowed = any(candidate[1].id == sku_id for candidate in allowed_rows)
        if not allowed:
            raise ApplicationError(
                "PUBLIC_SKU_NOT_FOUND",
                "Public SKU was not found.",
                kind="not_found",
            )
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
    translations, product_translations = _quote_translation_maps(
        session,
        tenant_id=tenant.id,
        rows=[row],
        source_locale=source_locale,
        target_locale=requested_locale,
        include_product_translations=True,
        include_sku_options=True,
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
        display_currency=tenant.default_currency.upper(),
        translation=translations.get(sku_id),
        product_translation=product_translations.get(row[2].id),
        pricing_markup_percent=pricing_markup_percent,
        pricing_overrides=pricing_overrides,
    )


def _item_response(row: PublicQuoteDraftItemRow) -> PublicQuoteDraftItemResponse:
    return PublicQuoteDraftItemResponse(
        id=row.id,
        sku_id=row.sku_id,
        product_id=row.product_id_snapshot,
        position=row.position,
        quantity=row.quantity,
        sku_code_snapshot=row.sku_code_snapshot,
        name_snapshot=row.name_snapshot,
        description_snapshot=row.description_snapshot,
        specification_snapshot=public_specification(row.specification_snapshot),
        option_values_snapshot=public_sku_option_values(
            row.option_values_snapshot or {}
        ),
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
        if (
            not label
            or label.startswith("_")
            or is_private_sku_option_key(label)
            or value in (None, "", [], {})
        ):
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


@lru_cache(maxsize=4)
def _cached_quote_language_pack(
    object_key: str,
    content_sha256: str,
    target_locale: str,
) -> dict[str, object]:
    """Load a versioned immutable pack once per API process.

    The cache key includes the content hash, so publishing a new package cannot
    accidentally reuse the preceding version. Failures are raised and therefore
    are not cached, allowing a transient R2 error to recover on the next request.
    """

    payload = load_language_pack_payload(
        configured_language_package_storage(),
        SimpleNamespace(
            object_key=object_key,
            content_sha256=content_sha256,
            target_locale=target_locale,
        ),
    )
    if payload is None:
        raise RuntimeError("catalog language package could not be loaded")
    return payload


def _quote_language_pack_payload(
    session: Session,
    *,
    tenant_id: UUID,
    target_locale: str,
) -> dict[str, object] | None:
    row = catalog_translation_repository.language_pack(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    if row is None:
        return None
    try:
        return _cached_quote_language_pack(
            row.object_key,
            row.content_sha256,
            row.target_locale,
        )
    except Exception as exc:
        logger.warning(
            "quotation could not load catalog language pack %s: %s",
            row.object_key,
            exc,
        )
        return None


def _pack_mapping(payload: dict[str, object] | None, key: str) -> dict[str, object]:
    value = payload.get(key) if payload is not None else None
    return value if isinstance(value, dict) else {}


def _pack_product_translation(
    entry: object,
    *,
    product_version: int,
) -> PublicProductTranslation | None:
    if not isinstance(entry, dict):
        return None
    if int(entry.get("product_version") or 0) != int(product_version):
        return None

    def clean_mapping(value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(source): str(localized).strip()
            for source, localized in value.items()
            if str(source).strip() and str(localized).strip()
        }

    tags = tuple(
        str(tag).strip()
        for tag in (entry.get("tags") or [])
        if str(tag).strip()
    )
    return PublicProductTranslation(
        name=str(entry.get("name") or "").strip(),
        description=(
            str(entry.get("description")).strip()
            if entry.get("description") not in (None, "")
            else None
        ),
        category=str(entry.get("category_label") or "").strip() or None,
        tags=tags,
        display_tag=str(entry.get("display_tag") or "").strip() or None,
        specifications=clean_mapping(entry.get("specifications")),
        option_labels=clean_mapping(entry.get("option_labels")),
        option_values=clean_mapping(entry.get("option_values")),
        complete=True,
    )


def _valid_pack_sku_entry(entry: object, row: object) -> dict[str, object] | None:
    if not isinstance(entry, dict):
        return None
    _offer, sku, product, _category = row
    if (
        entry.get("source_hash") != catalog_sku_package_source_hash(row)
        or int(entry.get("product_version") or 0) != int(product.current_version)
        or int(entry.get("sku_version") or 0) != int(sku.version)
    ):
        return None
    return entry


def _pack_sku_translation(
    entry: object,
    row: object,
) -> CatalogTranslationResult | None:
    """Convert an immutable language-pack SKU entry to the runtime shape.

    Language-pack ``source_hash`` fingerprints the complete package source,
    while ``_sku_response`` validates against the live catalog translation
    source hash.  Validate the former here, then expose the latter to the
    response layer so both paths use the same stale-data protection.
    """

    valid = _valid_pack_sku_entry(entry, row)
    if valid is None:
        return None
    source = catalog_translation_source(row)
    source_specification = str(
        (row[1].option_values or {}).get("规格名称") or ""
    ).strip() or None
    tags = tuple(
        str(tag).strip()
        for tag in (valid.get("tags") or [])
        if str(tag).strip()
    )
    return CatalogTranslationResult(
        sku_id=source.sku_id,
        source_hash=source.source_hash,
        name=str(valid.get("name") or "").strip() or source.name,
        description=(
            str(valid.get("description")).strip()
            if valid.get("description") not in (None, "")
            else source.description
        ),
        category=(
            str(valid.get("category_label") or "").strip()
            or source.category
        ),
        tags=tags or source.tags,
        display_tag=(
            str(valid.get("display_tag") or "").strip()
            or source.display_tag
        ),
        specification=(
            str(valid.get("specification") or "").strip()
            or source_specification
        ),
        complete=True,
    )


def _quote_translation_maps(
    session: Session,
    *,
    tenant_id: UUID,
    rows: list[object],
    source_locale: str,
    target_locale: str,
    include_product_translations: bool = True,
    include_sku_options: bool = True,
) -> tuple[
    dict[UUID, object],
    dict[UUID, PublicProductTranslation],
]:
    if target_locale == source_locale:
        return {}, {}

    payload = _quote_language_pack_payload(
        session,
        tenant_id=tenant_id,
        target_locale=target_locale,
    )
    pack_skus = _pack_mapping(payload, "skus")
    pack_products = _pack_mapping(payload, "products")
    sku_translations: dict[UUID, object] = {}
    product_translations: dict[UUID, PublicProductTranslation] = {}
    rows_by_product: dict[UUID, list[object]] = {}
    for row in rows:
        sku = row[1]
        product = row[2]
        if include_product_translations:
            rows_by_product.setdefault(product.id, []).append(row)
        translated_sku = _pack_sku_translation(
            pack_skus.get(str(sku.id)),
            row,
        )
        if translated_sku is not None:
            sku_translations[sku.id] = translated_sku
        if include_product_translations and product.id not in product_translations:
            translated_product = _pack_product_translation(
                pack_products.get(str(product.id)),
                product_version=product.current_version,
            )
            if translated_product is not None:
                product_translations[product.id] = translated_product

    missing_rows = [row for row in rows if row[1].id not in sku_translations]
    if missing_rows:
        stored = catalog_translation_repository.translation_map(
            session,
            tenant_id=tenant_id,
            sku_ids=[row[1].id for row in missing_rows],
            target_locale=target_locale,
        )
        for row in missing_rows:
            source = catalog_translation_source(row)
            translated = stored.get(row[1].id)
            if (
                translated is not None
                and translated.source_hash == source.source_hash
                and translated.product_version == row[2].current_version
                and translated.sku_version == row[1].version
            ):
                sku_translations[row[1].id] = translated

    missing_rows = [row for row in rows if row[1].id not in sku_translations]
    missing_groups = (
        [
            group
            for product_id, group in rows_by_product.items()
            if product_id not in product_translations
        ]
        if include_product_translations
        else []
    )
    if not missing_rows and not missing_groups:
        return sku_translations, product_translations

    translator = _live_translation_provider(
        session,
        source_locale=source_locale,
        target_locale=target_locale,
    )
    if missing_groups:
        product_translations.update(
            _live_product_translation_map(
                missing_groups,
                tenant_id=tenant_id,
                translator=translator,
                source_locale=source_locale,
                target_locale=target_locale,
                include_sku_options=include_sku_options,
                sku_translation_sink=sku_translations,
            )
        )
    missing_rows = [row for row in rows if row[1].id not in sku_translations]
    if missing_rows:
        sku_translations.update(
            _live_sku_translation_map(
                missing_rows,
                tenant_id=tenant_id,
                translator=translator,
                source_locale=source_locale,
                target_locale=target_locale,
                additional_values=None,
            )
        )
    return sku_translations, product_translations


def _quote_translation_value(
    translation: object | None,
    *keys: str,
) -> object | None:
    if translation is None:
        return None
    for key in keys:
        value = (
            translation.get(key)
            if isinstance(translation, dict)
            else getattr(translation, key, None)
        )
        if value not in (None, "", [], {}):
            return value
    return None


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
        quote_number=(getattr(draft, "quotation_number", None) or draft.request_number),
        request_number=draft.request_number,
        status=draft.status,
        customer_name=draft.customer_name,
        customer_company=draft.customer_company,
        customer_email=draft.customer_email,
        customer_phone=draft.customer_phone,
        notes=draft.notes,
        locale=_normalized_locale(
            getattr(draft, "document_locale", None),
            default="zh-CN",
        ),
        document_style=(getattr(draft, "document_style", None) or "indigo"),
        quote_template_id=getattr(draft, "quote_template_id", None),
        visible_columns=[
            str(field)
            for field in (getattr(draft, "quote_visible_columns", None) or [])
            if str(field).strip()
        ],
        currency=draft.currency,
        subtotal=draft.subtotal_amount,
        total=draft.estimated_total,
        total_amount=draft.estimated_total,
        valid_until=draft.expires_at,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        content_hash=draft.content_hash,
        disclaimer=PUBLIC_DRAFT_DISCLAIMER,
        disclaimer_version=draft.disclaimer_version,
        items=[_item_response(item) for item in items],
        download_token=raw_token,
        download_expires_at=token_expires_at,
        pdf_url=f"{document_base}/pdf" if raw_token else None,
        xlsx_url=f"{document_base}/xlsx" if raw_token else None,
    )


def _localized_quote_response(
    session: Session,
    *,
    draft: PublicQuoteDraftRow,
    items: list[PublicQuoteDraftItemRow],
    tenant: object,
) -> PublicQuoteDraftResponse:
    """Render the saved quote snapshot in its currently selected locale.

    A visitor may submit an inquiry in one language while the merchant
    prepares the commercial document in another.  Re-read the current
    translation package for the SKU/Product ids when available, but always
    fall back to the immutable snapshot so a catalog edit cannot erase an
    existing quote line.
    """
    response = _draft_response(draft, items)
    target_locale = response.locale
    source_locale = _normalized_locale(getattr(tenant, "default_locale", None))
    if target_locale == source_locale or not items:
        return response
    sku_ids = [item.sku_id for item in items]
    rows = repository.list_public_catalog_rows_by_sku_ids(
        session,
        tenant_id=draft.tenant_id,
        sku_ids=sku_ids,
        now=utcnow(),
    )
    row_by_sku = {row[1].id: row for row in rows}
    if not row_by_sku:
        return response
    try:
        sku_translations, product_translations = _quote_translation_maps(
            session,
            tenant_id=draft.tenant_id,
            rows=rows,
            source_locale=source_locale,
            target_locale=target_locale,
        )
    except Exception:
        # Export must remain available when an upstream translation provider is
        # temporarily unavailable. The saved quote snapshot is the fallback.
        logger.warning(
            "quote export translation unavailable; using saved snapshot",
            extra={"quote_draft_id": str(draft.id), "locale": target_locale},
            exc_info=True,
        )
        return response
    localized_items = []
    snapshot_items = (draft.snapshot or {}).get("items", []) if isinstance(draft.snapshot, dict) else []
    snapshot_by_position = {
        int(entry.get("position")): entry
        for entry in snapshot_items
        if isinstance(entry, dict) and str(entry.get("position", "")).isdigit()
    }
    for item in response.items:
        row = row_by_sku.get(item.sku_id)
        if row is None:
            localized_items.append(item)
            continue
        offer, sku, product, category = row
        sku_translation = sku_translations.get(sku.id)
        product_translation = product_translations.get(product.id)
        original_snapshot = snapshot_by_position.get(item.position, {})
        name_overridden = (
            "name" in original_snapshot
            and original_snapshot.get("name") != item.name_snapshot
        )
        description_overridden = (
            "description" in original_snapshot
            and original_snapshot.get("description") != item.description_snapshot
        )
        specification_overridden = (
            "specification" in original_snapshot
            and original_snapshot.get("specification") != item.specification_snapshot
        )
        category_overridden = (
            "category" in original_snapshot
            and original_snapshot.get("category") != item.category_snapshot
        )
        source_name = str(sku.name or product.name or item.name_snapshot).strip()
        translated_name = _quote_translation_value(sku_translation, "name")
        if translated_name is None:
            translated_name = _quote_translation_value(product_translation, "name")
        source_description = product.description or item.description_snapshot
        translated_description = _quote_translation_value(
            sku_translation, "description"
        ) or _quote_translation_value(product_translation, "description")
        source_category = _category_path(category) or item.category_snapshot
        translated_category = _quote_translation_value(
            sku_translation, "category_label", "category"
        ) or _quote_translation_value(product_translation, "category")
        source_tags = [
            str(tag).strip() for tag in (offer.tags or item.tags_snapshot) if str(tag).strip()
        ]
        translated_tags = _quote_translation_value(sku_translation, "tags")
        if translated_tags is None:
            translated_tags = _quote_translation_value(product_translation, "tags")
        source_options = public_sku_option_values(sku.option_values or {})
        source_options = {
            str(key): value
            for key, value in source_options.items()
            if str(key).strip() and not str(key).startswith("_")
        }
        localized_options = _localized_public_option_values(
            source_options,
            translation=product_translation,
        )
        source_specification = str(source_options.get("规格名称") or "").strip()
        translated_specification = _quote_translation_value(
            sku_translation, "specification"
        )
        if translated_specification in (None, "") and product_translation is not None:
            translated_specification = product_translation.specifications.get(
                source_specification,
                source_specification,
            )
        localized_items.append(
            item.model_copy(
                update={
                    "name_snapshot": (
                        item.name_snapshot
                        if name_overridden
                        else str(translated_name or source_name).strip()
                    ),
                    "description_snapshot": (
                        item.description_snapshot
                        if description_overridden
                        else (
                            str(translated_description).strip()
                            if translated_description not in (None, "")
                            else source_description
                        )
                    ),
                    "category_snapshot": (
                        item.category_snapshot
                        if category_overridden
                        else (
                            str(translated_category or source_category).strip()
                            if translated_category or source_category
                            else None
                        )
                    ),
                    "tags_snapshot": [
                        str(tag).strip()
                        for tag in (translated_tags or source_tags)
                        if str(tag).strip()
                    ],
                    "specification_snapshot": public_specification(
                        item.specification_snapshot
                    )
                    if specification_overridden
                    else public_specification(
                        (
                            str(translated_specification).strip()
                            if translated_specification not in (None, "")
                            else item.specification_snapshot
                        )
                    ),
                    "option_values_snapshot": public_sku_option_values(
                        localized_options or item.option_values_snapshot
                    ),
                }
            )
        )
    return response.model_copy(update={"items": localized_items})


def create_public_quote_draft(
    session: Session,
    *,
    slug: str,
    request: PublicQuoteDraftCreate,
    submitted_by_membership_id: UUID | None = None,
    submitted_by_tenant_id: UUID | None = None,
    submitted_by_user_id: UUID | None = None,
    visitor_token: str | None = None,
) -> PublicQuoteDraftResponse:
    tenant, profile = _resolve_store(session, slug=slug)
    source_locale, requested_locale, _available_locales = (
        _requested_storefront_locale(
            session,
            request.locale,
            tenant=tenant,
            profile=profile,
        )
    )
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
    pricing_markup_percent, pricing_overrides, hidden_product_ids = subaccount_price_rules(
        session,
        tenant_id=tenant.id,
        membership_id=submitted_by_membership_id,
        product_ids={row[2].id for row in rows},
    )
    if hidden_product_ids:
        rows = [row for row in rows if row[2].id not in hidden_product_ids]
        row_by_sku = {row[1].id: row for row in rows}
        missing = [str(sku_id) for sku_id in sku_ids if sku_id not in row_by_sku]
        if missing:
            raise ApplicationError(
                "PUBLIC_SKU_NOT_FOUND",
                "One or more selected products are not available for this account.",
                kind="not_found",
            )
    # Prices are deliberately not converted. The merchant's selected currency
    # controls only the presentation/snapshot currency used for new documents.
    currency = str(tenant.default_currency or "CNY").strip().upper()
    sku_translations, product_translations = _quote_translation_maps(
        session,
        tenant_id=tenant.id,
        rows=rows,
        source_locale=source_locale,
        target_locale=requested_locale,
    )
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
        unit_price = effective_subaccount_price(
            _money(Decimal(offer.unit_price)),
            markup_percent=pricing_markup_percent,
            override=pricing_overrides.get(product.id),
        )
        line_total = _money(unit_price * quantity)
        subtotal += line_total
        source_tags = [
            str(tag).strip() for tag in (offer.tags or []) if str(tag).strip()
        ]
        source_option_values = public_sku_option_values(sku.option_values or {})
        sku_translation = sku_translations.get(sku.id)
        product_translation = product_translations.get(product.id)
        localized_options = _localized_public_option_values(
            source_option_values,
            translation=product_translation,
        )
        option_values = {
            str(key): value
            for key, value in public_sku_option_values(localized_options).items()
            if str(key).strip() and not str(key).startswith("_")
        }
        source_public_options = {
            str(key): value
            for key, value in public_sku_option_values(source_option_values).items()
            if str(key).strip() and not str(key).startswith("_")
        }
        internal_marker = localized_options.get(_PUBLIC_OPTION_INTERNAL_KEY)
        marker = dict(internal_marker) if isinstance(internal_marker, dict) else {}
        marker["quote_source_option_values"] = source_public_options
        option_values[_PUBLIC_OPTION_INTERNAL_KEY] = marker

        source_specification = str(
            source_option_values.get("规格名称") or ""
        ).strip()
        translated_specification = _quote_translation_value(
            sku_translation,
            "specification",
        )
        if translated_specification in (None, "") and product_translation is not None:
            translated_specification = product_translation.specifications.get(
                source_specification,
                source_specification,
            )
        if translated_specification not in (None, ""):
            specification = str(translated_specification).strip() or None
        else:
            specification = _quote_specification(option_values)

        translated_tags = _quote_translation_value(sku_translation, "tags")
        if translated_tags is None and product_translation is not None:
            translated_tags = product_translation.tags
        tags = [
            str(tag).strip()
            for tag in (translated_tags or source_tags)
            if str(tag).strip()
        ]
        translated_name = _quote_translation_value(sku_translation, "name")
        if translated_name is None and product_translation is not None:
            translated_name = product_translation.name
        translated_description = _quote_translation_value(
            sku_translation,
            "description",
        )
        if translated_description is None and product_translation is not None:
            translated_description = product_translation.description
        translated_category = _quote_translation_value(
            sku_translation,
            "category_label",
            "category",
        )
        if translated_category is None and product_translation is not None:
            translated_category = product_translation.category
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
            name_snapshot=str(translated_name or sku.name or product.name).strip(),
            description_snapshot=(
                str(translated_description).strip()
                if translated_description not in (None, "")
                else product.description
            ),
            specification_snapshot=public_specification(specification),
            option_values_snapshot=public_sku_option_values(option_values),
            category_snapshot=(
                str(translated_category).strip()
                if translated_category not in (None, "")
                else _category_path(category) or None
            ),
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
                "specification": public_specification(specification),
                "option_values": public_sku_option_values(option_values),
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
        "document_locale": requested_locale,
        "source_locale": source_locale,
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
    visitor_token_hash = (
        _storefront_visitor_token_hash(visitor_token)
        if visitor_token is not None
        else None
    )
    draft = PublicQuoteDraftRow(
        id=draft_id,
        tenant_id=tenant.id,
        request_number=request_number,
        status="PENDING_CONFIRMATION",
        submitted_by_membership_id=submitted_by_membership_id,
        visitor_token_hash=visitor_token_hash,
        visitor_token_expires_at=(
            utcnow() + timedelta(days=180)
            if visitor_token_hash is not None
            else None
        ),
        customer_name=request.customer_name,
        customer_company=request.customer_company,
        customer_email=request.customer_email,
        customer_phone=request.customer_phone,
        notes=request.notes,
        document_locale=requested_locale,
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
    # Keep the original signed download URL usable for existing customers who
    # already received it at submission time.  New visitor-centre downloads
    # below are status-gated, and the storefront UI only reveals these actions
    # after confirmation.
    if draft is None or draft.status not in {
        "PENDING_CONFIRMATION",
        "CONFIRMED",
        "COMPLETED",
    }:
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
        quote=_localized_quote_response(
            session,
            draft=draft,
            items=items,
            tenant=tenant,
        ),
        excel_template=quote_template_use_cases.render_spec_for_template(
            session,
            tenant_id=tenant_id,
            template_id=getattr(draft, "quote_template_id", None),
        ),
        style=(getattr(draft, "document_style", None) or "indigo"),
    )


def get_storefront_visitor_quote_document(
    session: Session,
    *,
    slug: str,
    quote_draft_id: UUID,
    visitor_token: str,
) -> PublicQuoteDocument:
    """Return a confirmed quote document to the visitor who submitted it.

    The browser's visitor token is deliberately kept separate from the
    one-time download token returned at submission.  This lets a customer
    return to the visitor centre after a page refresh and download an approved
    quote without exposing a new long-lived document token in the quote list.
    """
    tenant, profile = _resolve_store(session, slug=slug)
    visitor_hash = _storefront_visitor_token_hash(visitor_token)
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant.id,
        quote_draft_id=quote_draft_id,
    )
    if (
        draft is None
        or draft.deleted_at is not None
        or draft.visitor_token_hash != visitor_hash
        or draft.visitor_token_expires_at is None
        or _as_utc(draft.visitor_token_expires_at) <= utcnow()
    ):
        raise ApplicationError(
            "DOWNLOAD_NOT_FOUND",
            "Download was not found.",
            kind="not_found",
        )
    if draft.status not in {"CONFIRMED", "COMPLETED"}:
        raise ApplicationError(
            "PUBLIC_QUOTE_NOT_CONFIRMED",
            "商家确认报价后才可以下载报价文件。",
            kind="conflict",
        )
    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant.id,
        quote_draft_id=quote_draft_id,
    )
    return PublicQuoteDocument(
        tenant_name=tenant.name,
        contact_email=profile.contact_email,
        contact_phone=profile.contact_phone,
        quote=_localized_quote_response(
            session,
            draft=draft,
            items=items,
            tenant=tenant,
        ),
        excel_template=quote_template_use_cases.render_spec_for_template(
            session,
            tenant_id=tenant.id,
            template_id=getattr(draft, "quote_template_id", None),
        ),
        style=(getattr(draft, "document_style", None) or "indigo"),
    )


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED", f"Permission is required: {code}", kind="forbidden"
        )


def _require_any(permissions: frozenset[str], *codes: str) -> None:
    if not any(code in permissions for code in codes):
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"One of these permissions is required: {', '.join(codes)}",
            kind="forbidden",
        )


def list_tenant_quote_drafts(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    limit: int,
) -> list[PublicQuoteDraftSummary]:
    # Incoming storefront quote requests are part of the sales inbox. A
    # member who can view inquiries may see the pending customer requests even
    # when they do not have access to the separate formal quotation ledger.
    _require_any(permissions, "quotation.view", "inquiry.view")
    return [
        PublicQuoteDraftSummary(
            id=row.id,
            quote_number=(getattr(row, "quotation_number", None) or row.request_number),
            status=row.status,
            customer_name=row.customer_name,
            customer_company=row.customer_company,
            locale=_normalized_locale(
                getattr(row, "document_locale", None),
                default="zh-CN",
            ),
            currency=row.currency,
            total_amount=row.estimated_total,
            valid_until=row.expires_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in repository.list_quote_drafts(
            session, tenant_id=tenant_id, limit=limit
        )
    ]


def _storefront_visitor_token_hash(raw_token: str) -> str:
    token = raw_token.strip()
    if len(token) < 32 or len(token) > 500:
        raise ApplicationError(
            "STOREFRONT_VISITOR_SESSION_INVALID",
            "访客会话已失效，请刷新页面后重试。",
            kind="unauthorized",
        )
    return hash_secret(token)


def list_storefront_visitor_quote_drafts(
    session: Session,
    *,
    slug: str,
    visitor_token: str,
    limit: int = 100,
) -> list[PublicQuoteDraftSummary]:
    tenant, _profile = _resolve_store(session, slug=slug)
    rows = repository.list_quote_drafts_by_visitor_token_hash(
        session,
        tenant_id=tenant.id,
        visitor_token_hash=_storefront_visitor_token_hash(visitor_token),
        now=utcnow(),
        limit=limit,
    )
    return [
        PublicQuoteDraftSummary(
            id=row.id,
            quote_number=(getattr(row, "quotation_number", None) or row.request_number),
            status=row.status,
            customer_name=row.customer_name,
            customer_company=row.customer_company,
            locale=_normalized_locale(
                getattr(row, "document_locale", None),
                default="zh-CN",
            ),
            currency=row.currency,
            total_amount=row.estimated_total,
            valid_until=row.expires_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def update_tenant_quote_draft_status(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
    request: PublicQuoteDraftStatusUpdate,
) -> PublicQuoteDraftResponse:
    _require(permissions, "quotation.create")
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    if draft is None or draft.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    transitions = {
        "PENDING_CONFIRMATION": {"CONFIRMED", "CANCELLED"},
        "CONFIRMED": {"COMPLETED", "CANCELLED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
        "EXPIRED": set(),
    }
    if request.status != draft.status and request.status not in transitions.get(
        draft.status,
        set(),
    ):
        raise ApplicationError(
            "PUBLIC_QUOTE_STATUS_TRANSITION_INVALID",
            "当前询价单状态不能执行此操作。",
            kind="conflict",
        )
    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    now = utcnow()
    order_record = repository.get_storefront_order_record_by_quote(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    order_changed = False
    if request.status == "CONFIRMED" and order_record is None:
        order_record = _create_storefront_order_record(
            session,
            draft=draft,
            items=items,
            membership_id=membership_id,
            confirmed_at=now if draft.status == "PENDING_CONFIRMATION" else draft.updated_at,
        )
        order_changed = True
    elif draft.status == "CONFIRMED" and request.status in {"COMPLETED", "CANCELLED"}:
        if order_record is None:
            order_record = _create_storefront_order_record(
                session,
                draft=draft,
                items=items,
                membership_id=membership_id,
                confirmed_at=draft.updated_at,
            )
        order_record.status = request.status
        order_record.updated_at = now
        if request.status == "COMPLETED":
            order_record.completed_at = now
        else:
            order_record.cancelled_at = now
        order_changed = True
    draft_changed = request.status != draft.status
    if draft_changed:
        transitioned = repository.transition_quote_draft_status(
            session,
            tenant_id=tenant_id,
            quote_draft_id=quote_draft_id,
            expected_status=draft.status,
            target_status=request.status,
            updated_at=now,
        )
        if not transitioned:
            session.rollback()
            raise ApplicationError(
                "PUBLIC_QUOTE_STATUS_TRANSITION_CONFLICT",
                "询价单状态已由其他操作更新，请刷新后重试。",
                kind="conflict",
            )
        draft.status = request.status
        draft.updated_at = now
    if draft_changed or order_changed:
        # The draft and its order fact are committed atomically.  The explicit
        # order_changed branch also repairs an older confirmed draft that did
        # not yet have an order record.
        session.commit()
        session.refresh(draft)
    return _draft_response(draft, items)


def _create_storefront_order_record(
    session: Session,
    *,
    draft: PublicQuoteDraftRow,
    items: list[PublicQuoteDraftItemRow],
    membership_id: UUID,
    confirmed_at: datetime,
) -> StorefrontOrderRecordRow:
    if not items:
        raise ApplicationError(
            "PUBLIC_QUOTE_ITEMS_MISSING",
            "询价单没有可确认的商品明细。",
            kind="conflict",
        )
    snapshot_items = [
        {
            "position": item.position,
            "sku_id": str(item.sku_id),
            "product_id": str(item.product_id_snapshot),
            "product_version": item.product_version,
            "sku_version": item.sku_version,
            "sku_code": item.sku_code_snapshot,
            "name": item.name_snapshot,
            "description": item.description_snapshot,
            "specification": item.specification_snapshot,
            "option_values": item.option_values_snapshot,
            "category": item.category_snapshot,
            "tags": item.tags_snapshot,
            "image_url": item.image_url_snapshot,
            "minimum_order_quantity": str(item.minimum_order_quantity),
            "quantity": str(item.quantity),
            "unit_code": item.unit_code_snapshot,
            "currency": item.currency_snapshot,
            "unit_price": str(item.unit_price_snapshot),
            "line_total": str(item.line_total),
        }
        for item in items
    ]
    snapshot = {
        "schema_version": "storefront-order-v1",
        "source_quote": {
            "id": str(draft.id),
            "number": draft.request_number,
            "quotation_number": getattr(draft, "quotation_number", None),
            "content_hash": draft.content_hash,
        },
        "customer": {
            "name": draft.customer_name,
            "company": draft.customer_company,
            "email": draft.customer_email,
            "phone": draft.customer_phone,
            "submitted_by_membership_id": (
                str(draft.submitted_by_membership_id)
                if draft.submitted_by_membership_id
                else None
            ),
        },
        "document_locale": draft.document_locale,
        "currency": draft.currency,
        "subtotal_amount": str(draft.subtotal_amount),
        "total_amount": str(draft.estimated_total),
        "items": snapshot_items,
        "confirmation": {
            "confirmed_at": confirmed_at.isoformat(),
            "confirmed_by_membership_id": str(membership_id),
        },
    }
    content_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    record = StorefrontOrderRecordRow(
        tenant_id=draft.tenant_id,
        source_quote_draft_id=draft.id,
        order_number=(getattr(draft, "quotation_number", None) or draft.request_number),
        status="CONFIRMED",
        submitted_by_membership_id=draft.submitted_by_membership_id,
        customer_name=draft.customer_name,
        customer_company=draft.customer_company,
        customer_email=draft.customer_email,
        customer_phone=draft.customer_phone,
        document_locale=draft.document_locale,
        currency=draft.currency,
        subtotal_amount=draft.subtotal_amount,
        total_amount=draft.estimated_total,
        item_count=len(items),
        total_quantity=sum((item.quantity for item in items), Decimal("0")),
        confirmed_by_membership_id=membership_id,
        confirmed_at=confirmed_at,
        snapshot=snapshot,
        content_hash=content_hash,
    )
    repository.add_storefront_order_record(session, record=record)
    return record


def _reporting_timezone(configured: str | None = None) -> ZoneInfo:
    configured = (
        configured or os.getenv("ORDER_REPORTING_TIMEZONE", "Asia/Shanghai")
    ).strip()
    try:
        return ZoneInfo(configured)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown ORDER_REPORTING_TIMEZONE=%s; falling back to UTC", configured)
        return ZoneInfo("UTC")


def _order_period_statistics(
    session: Session,
    *,
    tenant_id: UUID,
    start_at: datetime,
    end_at: datetime,
) -> StorefrontOrderPeriodStatistics:
    by_currency: dict[str, dict[str, Decimal | int]] = {}
    completed_count = 0
    cancelled_count = 0
    for currency, status, count, amount in repository.storefront_order_statistics_rows(
        session,
        tenant_id=tenant_id,
        start_at=start_at,
        end_at=end_at,
    ):
        count = int(count)
        amount = Decimal(amount)
        if status == "CANCELLED":
            cancelled_count += count
            continue
        row = by_currency.setdefault(
            currency,
            {
                "total_amount": Decimal("0"),
                "completed_amount": Decimal("0"),
                "order_count": 0,
            },
        )
        row["total_amount"] = Decimal(row["total_amount"]) + amount
        row["order_count"] = int(row["order_count"]) + count
        if status == "COMPLETED":
            row["completed_amount"] = Decimal(row["completed_amount"]) + amount
            completed_count += count
    amounts = [
        StorefrontOrderCurrencyStatistics(
            currency=currency,
            total_amount=Decimal(values["total_amount"]),
            completed_amount=Decimal(values["completed_amount"]),
            order_count=int(values["order_count"]),
        )
        for currency, values in sorted(by_currency.items())
    ]
    return StorefrontOrderPeriodStatistics(
        start_at=start_at,
        end_at=end_at,
        order_count=sum(item.order_count for item in amounts),
        completed_order_count=completed_count,
        cancelled_order_count=cancelled_count,
        amounts=amounts,
    )


def get_tenant_order_statistics(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    now: datetime | None = None,
) -> StorefrontOrderStatistics:
    _require(permissions, "quotation.view")
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id)
    timezone = _reporting_timezone(tenant.timezone if tenant is not None else None)
    local_now = (now or utcnow()).astimezone(timezone)
    month_start_local = local_now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    if month_start_local.month == 12:
        month_end_local = month_start_local.replace(
            year=month_start_local.year + 1,
            month=1,
        )
    else:
        month_end_local = month_start_local.replace(month=month_start_local.month + 1)
    year_start_local = month_start_local.replace(month=1)
    year_end_local = year_start_local.replace(year=year_start_local.year + 1)
    month_start = month_start_local.astimezone(UTC)
    month_end = month_end_local.astimezone(UTC)
    year_start = year_start_local.astimezone(UTC)
    year_end = year_end_local.astimezone(UTC)
    return StorefrontOrderStatistics(
        timezone=timezone.key,
        current_month=_order_period_statistics(
            session,
            tenant_id=tenant_id,
            start_at=month_start,
            end_at=month_end,
        ),
        current_year=_order_period_statistics(
            session,
            tenant_id=tenant_id,
            start_at=year_start,
            end_at=year_end,
        ),
    )


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
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id)
    return (
        _localized_quote_response(session, draft=draft, items=items, tenant=tenant)
        if tenant is not None
        else _draft_response(draft, items)
    )


def update_tenant_quote_draft_settings(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
    request: PublicQuoteDraftSettingsUpdate,
) -> PublicQuoteDraftResponse:
    """Save the presentation settings used by the quote document workspace."""
    _require(permissions, "quotation.create")
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    if draft is None or draft.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id)
    profile = repository.find_profile_by_tenant(session, tenant_id=tenant_id)
    if tenant is None or profile is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND",
            "Merchant profile was not found.",
            kind="not_found",
        )
    _source_locale, requested_locale, _available_locales = _requested_storefront_locale(
        session,
        request.locale,
        tenant=tenant,
        profile=profile,
    )
    if request.template_id is not None:
        template = quote_template_repository.get_for_tenant(
            session,
            tenant_id=tenant_id,
            template_id=request.template_id,
        )
        if template is None or not template.column_mappings:
            raise ApplicationError(
                "QUOTE_EXCEL_TEMPLATE_NOT_READY",
                "所选 Excel 模板不存在或尚未完成字段映射。",
                kind="conflict",
            )
    quote_number = (request.quote_number or "").strip()
    if not quote_number:
        quote_number = getattr(draft, "quotation_number", None) or draft.request_number
    occupied = repository.get_quote_draft_by_quotation_number(
        session,
        tenant_id=tenant_id,
        quotation_number=quote_number,
    )
    if occupied is not None and occupied.id != draft.id:
        raise ApplicationError(
            "QUOTE_NUMBER_CONFLICT",
            "报价单编号已被当前商家使用，请更换一个编号。",
            kind="conflict",
        )
    draft.document_locale = requested_locale
    draft.document_style = request.style
    draft.quote_template_id = request.template_id
    draft.quotation_number = quote_number
    if request.visible_columns is not None:
        draft.quote_visible_columns = list(dict.fromkeys(request.visible_columns)) or None
    draft.updated_at = utcnow()
    session.commit()
    session.refresh(draft)
    updated_items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    return _localized_quote_response(
        session,
        draft=draft,
        items=updated_items,
        tenant=tenant,
    )


def convert_tenant_quote_draft_currency(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
    request: PublicQuoteDraftCurrencyConversion,
) -> PublicQuoteDraftResponse:
    """Convert all current quote-line prices using the cached market rate."""

    _require(permissions, "quotation.create")
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    if draft is None or draft.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    if draft.status != "PENDING_CONFIRMATION":
        raise ApplicationError(
            "PUBLIC_QUOTE_CURRENCY_EDIT_NOT_ALLOWED",
            "只有待确认状态的报价单可以进行币种换算。",
            kind="conflict",
        )

    source_currency = str(draft.currency or "CNY").strip().upper()
    target_currency = str(request.target_currency or "").strip().upper()
    if source_currency == target_currency:
        return _quote_draft_item_edit_response(
            session,
            tenant_id=tenant_id,
            draft=draft,
        )

    market = get_dashboard_market_snapshot()
    factor = _currency_conversion_factor(
        market,
        source_currency=source_currency,
        target_currency=target_currency,
    )
    if factor is None:
        raise ApplicationError(
            "QUOTE_CURRENCY_RATE_UNAVAILABLE",
            f"当前暂未取得 {source_currency} 到 {target_currency} 的汇率，请稍后重试。",
            kind="conflict",
        )

    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    for item in items:
        item.unit_price_snapshot = _money(
            Decimal(item.unit_price_snapshot) * factor
        )
        item.currency_snapshot = target_currency
    draft.currency = target_currency
    rate_date = next(
        (
            str(getattr(item, "rate_date", "")).strip()
            for item in getattr(market, "exchange_rates", ())
            if str(getattr(item, "currency", "")).upper()
            in {source_currency, target_currency}
            and getattr(item, "rate_date", None)
        ),
        "",
    )
    _recalculate_quote_draft_totals(
        draft,
        items,
        conversion={
            "from": source_currency,
            "to": target_currency,
            "factor": str(factor),
            "rate_date": rate_date,
            "source": str(getattr(market, "rate_source", "market")),
            "converted_at": utcnow().isoformat(),
        },
    )
    session.commit()
    return _quote_draft_item_edit_response(
        session,
        tenant_id=tenant_id,
        draft=draft,
    )


def _recalculate_quote_draft_totals(
    draft: PublicQuoteDraftRow,
    items: list[PublicQuoteDraftItemRow],
    *,
    conversion: dict[str, str] | None = None,
) -> None:
    for item in items:
        item.line_total = _money(
            Decimal(item.unit_price_snapshot) * Decimal(item.quantity)
        )
    subtotal = _money(
        sum((Decimal(item.line_total) for item in items), Decimal("0"))
    )
    draft.subtotal_amount = subtotal
    draft.estimated_total = subtotal
    draft.updated_at = utcnow()
    _refresh_quote_draft_snapshot(draft, items, conversion=conversion)


def _refresh_quote_draft_snapshot(
    draft: PublicQuoteDraftRow,
    items: list[PublicQuoteDraftItemRow],
    *,
    conversion: dict[str, str] | None = None,
) -> None:
    """Keep the audit snapshot aligned with editable quote-line values."""

    source = draft.snapshot if isinstance(draft.snapshot, dict) else {}
    snapshot = dict(source)
    existing_items = snapshot.get("items")
    by_position = {
        int(entry.get("position")): dict(entry)
        for entry in existing_items
        if isinstance(entry, dict) and str(entry.get("position", "")).isdigit()
    } if isinstance(existing_items, list) else {}
    snapshot_items: list[dict[str, object]] = []
    for item in items:
        entry = by_position.get(item.position, {})
        entry.update(
            {
                "position": item.position,
                "sku_id": str(item.sku_id),
                "product_id": str(item.product_id_snapshot),
                "product_version": item.product_version,
                "sku_version": item.sku_version,
                "sku_code": item.sku_code_snapshot,
                "name": item.name_snapshot,
                "description": item.description_snapshot,
                "specification": item.specification_snapshot,
                "option_values": item.option_values_snapshot,
                "category": item.category_snapshot,
                "tags": item.tags_snapshot,
                "image_url": item.image_url_snapshot,
                "quantity": str(item.quantity),
                "unit_code": item.unit_code_snapshot,
                "currency": item.currency_snapshot,
                "unit_price": str(item.unit_price_snapshot),
                "line_total": str(item.line_total),
            }
        )
        snapshot_items.append(entry)
    snapshot["items"] = snapshot_items
    snapshot["currency"] = draft.currency
    snapshot["subtotal_amount"] = str(draft.subtotal_amount)
    snapshot["estimated_total"] = str(draft.estimated_total)
    if conversion is not None:
        snapshot["currency_conversion"] = conversion
    draft.snapshot = snapshot
    draft.content_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _market_currency_rate(snapshot: object, currency: str) -> Decimal | None:
    for item in getattr(snapshot, "exchange_rates", ()):
        if str(getattr(item, "currency", "")).upper() == currency:
            value = getattr(item, "rate", None)
            if value is not None and Decimal(value) > 0:
                return Decimal(value)
    return None


def _currency_conversion_factor(
    snapshot: object,
    *,
    source_currency: str,
    target_currency: str,
) -> Decimal | None:
    source = "CNY" if source_currency == "RMB" else source_currency
    target = "CNY" if target_currency == "RMB" else target_currency
    if source == target:
        return Decimal("1")
    # Market rates are expressed as CNY per unit of currency. To convert an
    # amount from source currency to target currency, multiply by source CNY
    # value and divide by target CNY value.
    source_rate = Decimal("1") if source == "CNY" else _market_currency_rate(snapshot, source)
    target_rate = Decimal("1") if target == "CNY" else _market_currency_rate(snapshot, target)
    if source_rate is None or target_rate is None:
        return None
    return source_rate / target_rate


def _quote_draft_item_edit_response(
    session: Session,
    *,
    tenant_id: UUID,
    draft: PublicQuoteDraftRow,
) -> PublicQuoteDraftResponse:
    session.refresh(draft)
    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=draft.id,
    )
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id)
    return (
        _localized_quote_response(session, draft=draft, items=items, tenant=tenant)
        if tenant is not None
        else _draft_response(draft, items)
    )


def update_tenant_quote_draft_items(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
    request: PublicQuoteDraftItemsUpdate,
) -> PublicQuoteDraftResponse:
    """Persist customer-facing edits made directly in the quote preview."""

    _require(permissions, "quotation.create")
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    if draft is None or draft.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    if draft.status != "PENDING_CONFIRMATION":
        raise ApplicationError(
            "PUBLIC_QUOTE_EDIT_NOT_ALLOWED",
            "只有待确认状态的报价单可以编辑商品信息。",
            kind="conflict",
        )
    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    items_by_id = {item.id: item for item in items}
    for patch in request.items:
        item = items_by_id.get(patch.item_id)
        if item is None or item.deleted_at is not None:
            raise ApplicationError(
                "PUBLIC_QUOTE_ITEM_NOT_FOUND",
                "报价单商品明细不存在。",
                kind="not_found",
            )
        fields = patch.model_fields_set
        if "unit_price" in fields:
            item.unit_price_snapshot = _money(patch.unit_price or Decimal("0"))
        if "quantity" in fields:
            item.quantity = patch.quantity or Decimal("0.000001")
        if "name" in fields:
            item.name_snapshot = patch.name or ""
        if "description" in fields:
            item.description_snapshot = patch.description
        if "specification" in fields:
            item.specification_snapshot = patch.specification
        if "category" in fields:
            item.category_snapshot = patch.category
        if "unit_code" in fields:
            item.unit_code_snapshot = patch.unit_code or "piece"

    _recalculate_quote_draft_totals(draft, items)
    session.commit()
    return _quote_draft_item_edit_response(
        session,
        tenant_id=tenant_id,
        draft=draft,
    )


def adjust_tenant_quote_draft_prices(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
    request: PublicQuoteDraftPriceAdjustment,
) -> PublicQuoteDraftResponse:
    """Apply one signed percentage to every quote-line unit price."""

    _require(permissions, "quotation.create")
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    if draft is None or draft.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    if draft.status != "PENDING_CONFIRMATION":
        raise ApplicationError(
            "PUBLIC_QUOTE_EDIT_NOT_ALLOWED",
            "只有待确认状态的报价单可以调整商品价格。",
            kind="conflict",
        )
    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    multiplier = (Decimal("100") + request.percentage) / Decimal("100")
    for item in items:
        item.unit_price_snapshot = _money(
            Decimal(item.unit_price_snapshot) * multiplier
        )
    _recalculate_quote_draft_totals(draft, items)
    session.commit()
    return _quote_draft_item_edit_response(
        session,
        tenant_id=tenant_id,
        draft=draft,
    )


def update_tenant_quote_draft_item_price(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    quote_draft_id: UUID,
    item_id: UUID,
    request: PublicQuoteDraftItemPriceUpdate,
    sync_to_catalog: bool = False,
) -> PublicQuoteDraftResponse:
    """Update a quote-line price, optionally publishing the same price to the SKU.

    A quote override is deliberately kept on the draft item and never changes
    the immutable storefront submission snapshot.  The catalog write is a
    separate, explicitly requested action and therefore requires the stronger
    ``catalog.publish`` permission.
    """

    _require(permissions, "quotation.create")
    if sync_to_catalog:
        _require(permissions, "catalog.publish")
    draft = repository.get_quote_draft(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        for_update=True,
    )
    if draft is None or draft.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_DRAFT_NOT_FOUND",
            "Public quote draft was not found.",
            kind="not_found",
        )
    if draft.status != "PENDING_CONFIRMATION":
        raise ApplicationError(
            "PUBLIC_QUOTE_PRICE_EDIT_NOT_ALLOWED",
            "只有待确认状态的报价单可以修改商品价格。",
            kind="conflict",
        )
    item = repository.get_quote_draft_item(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
        item_id=item_id,
        for_update=True,
    )
    if item is None or item.deleted_at is not None:
        raise ApplicationError(
            "PUBLIC_QUOTE_ITEM_NOT_FOUND",
            "报价单商品明细不存在。",
            kind="not_found",
        )

    unit_price = _money(request.unit_price)
    item.unit_price_snapshot = unit_price
    item.line_total = _money(unit_price * Decimal(item.quantity))
    items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    draft.subtotal_amount = _money(sum((Decimal(row.line_total) for row in items), Decimal("0")))
    draft.estimated_total = draft.subtotal_amount
    draft.updated_at = utcnow()

    if sync_to_catalog:
        # Reuse the canonical public-offer writer so tags, publication state,
        # audit events, search invalidation and optimistic catalog locks stay
        # identical to the product-management screen.  Preserve every field
        # except the explicitly changed price.
        from ..product_center_schemas import PublicCatalogOfferUpsertRequest
        from ..repositories import product_center_repository
        from . import product_center as product_center_use_cases

        offer = product_center_repository.get_public_offer(
            session,
            tenant_id=tenant_id,
            sku_id=item.sku_id,
        )
        offer_request = PublicCatalogOfferUpsertRequest(
            unit_price=unit_price,
            currency=(offer.currency if offer is not None else item.currency_snapshot),
            tags=list(offer.tags or []) if offer is not None else [],
            display_tag=offer.display_tag if offer is not None else None,
            tag_color=offer.tag_color if offer is not None else None,
            publication_status=(offer.publication_status if offer is not None else "DRAFT"),
            valid_from=offer.valid_from if offer is not None else None,
            valid_to=offer.valid_to if offer is not None else None,
        )
        product_center_use_cases.upsert_public_offer(
            session,
            tenant_id=tenant_id,
            membership_id=membership_id,
            permissions=permissions,
            sku_id=item.sku_id,
            request=offer_request,
        )
    else:
        session.commit()

    session.refresh(draft)
    updated_items = repository.list_quote_draft_items(
        session,
        tenant_id=tenant_id,
        quote_draft_id=quote_draft_id,
    )
    tenant = repository.get_active_tenant(session, tenant_id=tenant_id)
    return (
        _localized_quote_response(session, draft=draft, items=updated_items, tenant=tenant)
        if tenant is not None
        else _draft_response(draft, updated_items)
    )


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
        quote=_localized_quote_response(
            session,
            draft=draft,
            items=items,
            tenant=tenant,
        ),
        excel_template=quote_template_use_cases.render_spec_for_template(
            session,
            tenant_id=tenant_id,
            template_id=getattr(draft, "quote_template_id", None),
        ),
        style=(getattr(draft, "document_style", None) or "indigo"),
    )
