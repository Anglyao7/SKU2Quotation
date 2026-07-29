from __future__ import annotations

import hashlib
import json
import logging
import math
import os
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
    PublicSkuPage,
    PublicSkuResponse,
    PublicStoreResponse,
)
from ..repositories import public_catalog_repository as repository
from ..services.catalog_translation import (
    CatalogTranslationResult,
    catalog_translation_source,
    translate_catalog_sources,
    translate_catalog_values,
    translation_batches,
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


MONEY = Decimal("0.01")
PUBLIC_TOKEN_SEPARATOR = "."
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CustomerQuoteSubmitter:
    membership_id: UUID
    tenant_id: UUID
    user_id: UUID


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
    normalized = (value or default).strip().replace("_", "-")
    aliases = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "en": "en-US",
        "en-us": "en-US",
    }
    locale = aliases.get(normalized.casefold())
    if locale is None:
        raise ApplicationError(
            "PUBLIC_LOCALE_UNSUPPORTED",
            "The requested storefront language is not supported.",
        )
    return locale


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
    source_locale = _normalized_locale(tenant.default_locale)
    requested_locale = _normalized_locale(locale, default=source_locale)
    available_locales = [source_locale]
    if catalog_translation_is_configured() and source_locale != "en-US":
        available_locales.append("en-US")
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
        source_locale=source_locale,
        locale=locale,
        translation_status=(
            "SOURCE"
            if locale == source_locale
            else "TRANSLATED"
            if translated
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


def _live_sku_translation_map(
    rows: list[object],
    *,
    translator: TranslationProvider | None,
    source_locale: str,
    target_locale: str,
) -> dict[UUID, CatalogTranslationResult]:
    if translator is None or not rows:
        return {}
    sources = [catalog_translation_source(row) for row in rows]
    results: list[CatalogTranslationResult] = []
    try:
        for batch in translation_batches(
            sources,
            max_items=_positive_int_environment(
                "PUBLIC_LIVE_TRANSLATION_BATCH_SIZE",
                50,
                maximum=100,
            ),
            max_characters=_positive_int_environment(
                "PUBLIC_LIVE_TRANSLATION_BATCH_CHARACTERS",
                2_800,
                maximum=100_000,
            ),
        ):
            results.extend(
                translate_catalog_sources(
                    translator,
                    batch,
                    source_locale=source_locale,
                    target_locale=target_locale,
                )
            )
    except TranslationProviderError as exc:
        logger.warning("live SKU translation failed; using source text: %s", exc)
        return {}
    return {result.sku_id: result for result in results}


def _live_category_labels(
    categories: list[str],
    *,
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
    try:
        translated_segments = translate_catalog_values(
            translator,
            segments,
            source_locale=source_locale,
            target_locale=target_locale,
        )
    except TranslationProviderError as exc:
        logger.warning("live category translation failed; using source text: %s", exc)
        return {}
    segment_labels = dict(zip(segments, translated_segments, strict=True))
    return {
        category: "/".join(
            segment_labels.get(segment.strip(), segment.strip())
            for segment in category.replace("／", "/").split("/")
            if segment.strip()
        )
        for category in categories
    }


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
    source_locale = _normalized_locale(tenant.default_locale)
    requested_locale = _normalized_locale(locale, default=source_locale)
    now = utcnow()
    wanted_tags = _normalize_tags(tags)
    all_categories = repository.list_catalog_categories(
        session, tenant_id=tenant.id
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
        facet_tags = repository.list_public_catalog_tags(
            session,
            tenant_id=tenant.id,
            now=now,
            query="",
            category=None,
        )
    else:
        visible_category_ids = set()
        facet_tags = []

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
        translator=translator,
        source_locale=source_locale,
        target_locale=requested_locale,
    )
    category_labels = (
        _live_category_labels(
            categories,
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
        tags=facet_tags,
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
    tenant, _profile = _resolve_store(session, slug=slug)
    source_locale = _normalized_locale(tenant.default_locale)
    requested_locale = _normalized_locale(locale, default=source_locale)
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
    )
