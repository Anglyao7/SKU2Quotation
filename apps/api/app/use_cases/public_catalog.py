from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
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
    PublicSkuPage,
    PublicSkuResponse,
    PublicStoreResponse,
)
from ..repositories import public_catalog_repository as repository
from ..services.auth.tokens import hash_secret, new_secret


MONEY = Decimal("0.01")
PUBLIC_TOKEN_SEPARATOR = "."


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
        session, tenant_id=profile.tenant_id, slug=normalized
    )
    if tenant is None:
        raise ApplicationError("STORE_NOT_FOUND", "Store was not found.", kind="not_found")
    return tenant, profile


def get_store(session: Session, *, slug: str) -> PublicStoreResponse:
    tenant, profile = _resolve_store(session, slug=slug)
    return PublicStoreResponse(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        description=profile.description,
        logo_url=profile.logo_url,
        contact_email=profile.contact_email,
        contact_phone=profile.contact_phone,
        default_currency=tenant.default_currency,
        locale=tenant.default_locale,
    )


def _sku_response(row: object, *, image: object | None, slug: str) -> PublicSkuResponse:
    offer, sku, product, category = row
    moq = Decimal(sku.default_moq or 1)
    if moq <= 0:
        moq = Decimal("1")
    tags = [str(tag).strip() for tag in (offer.tags or []) if str(tag).strip()]
    return PublicSkuResponse(
        id=sku.id,
        product_id=product.id,
        sku_code=sku.sku_code,
        name=sku.name or product.name,
        description=product.description,
        category=category.name if category is not None else None,
        tags=list(dict.fromkeys(tags)),
        price=_money(Decimal(offer.unit_price)),
        currency=offer.currency,
        moq=moq,
        unit_code=sku.moq_unit or product.default_unit or "piece",
        image_url=_public_image_url(image, slug=slug),
        product_version=product.current_version,
        sku_version=sku.version,
    )


def list_public_skus(
    session: Session,
    *,
    slug: str,
    query: str,
    category: str | None,
    tags: list[str],
    semantic: bool,
    page: int,
    page_size: int,
) -> PublicSkuPage:
    tenant, _profile = _resolve_store(session, slug=slug)
    rows = repository.list_public_catalog_rows(
        session,
        tenant_id=tenant.id,
        now=utcnow(),
        query="" if semantic and query.strip() else query,
        category=category,
    )
    if semantic and query.strip():
        normalized_query = query.casefold().strip()
        tokens = [
            token
            for token in re.split(r"[\s,，/|]+", normalized_query)
            if token
        ]

        def relevance(row: object) -> int:
            offer, sku, product, row_category = row
            sku_code = str(sku.sku_code).casefold()
            sku_name = str(sku.name or "").casefold()
            product_name = str(product.name).casefold()
            description = str(product.description or "").casefold()
            category_name = str(row_category.name if row_category else "").casefold()
            tag_values = [str(tag).casefold() for tag in (offer.tags or [])]
            fields = [sku_code, sku_name, product_name, description, category_name, *tag_values]
            score = 100 if sku_code == normalized_query else 0
            score += 50 if normalized_query in sku_code else 0
            score += 40 if normalized_query in sku_name or normalized_query in product_name else 0
            score += 35 if any(normalized_query in tag for tag in tag_values) else 0
            for token in tokens:
                score += 12 if token in sku_code else 0
                score += 8 if token in sku_name or token in product_name else 0
                score += 7 if any(token in tag for tag in tag_values) else 0
                score += 3 if token in description or token in category_name else 0
            return score if all(any(token in field for field in fields) for token in tokens) else 0

        scored = [(relevance(row), row) for row in rows]
        rows = [
            row
            for score, row in sorted(
                scored,
                key=lambda item: (
                    -item[0],
                    str(item[1][2].name).casefold(),
                    str(item[1][1].sku_code).casefold(),
                ),
            )
            if score > 0
        ]
    categories = sorted(
        {row[3].name for row in rows if row[3] is not None}, key=str.casefold
    )
    facet_tags = sorted(
        {
            str(tag).strip()
            for row in rows
            for tag in (row[0].tags or [])
            if str(tag).strip()
        },
        key=str.casefold,
    )
    wanted_tags = _normalize_tags(tags)
    if wanted_tags:
        rows = [
            row
            for row in rows
            if wanted_tags.issubset(
                {str(tag).strip().casefold() for tag in (row[0].tags or [])}
            )
        ]
    total = len(rows)
    start = (page - 1) * page_size
    selected = rows[start : start + page_size]
    images = repository.approved_image_map(
        session,
        tenant_id=tenant.id,
        product_ids={row[2].id for row in selected},
    )
    return PublicSkuPage(
        items=[
            _sku_response(row, image=images.get(row[2].id), slug=tenant.slug)
            for row in selected
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        categories=categories,
        tags=facet_tags,
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
        minimum_order_quantity=row.minimum_order_quantity,
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
    session: Session, *, slug: str, request: PublicQuoteDraftCreate
) -> PublicQuoteDraftResponse:
    tenant, _profile = _resolve_store(session, slug=slug)
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
        minimum = Decimal(sku.default_moq or 1)
        if minimum <= 0:
            minimum = Decimal("1")
        quantity = Decimal(cart_item.quantity)
        if quantity < minimum:
            raise ApplicationError(
                "PUBLIC_CART_BELOW_MOQ",
                f"Quantity for {sku.sku_code} must be at least {minimum}.",
            )
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
            category_snapshot=category.name if category is not None else None,
            tags_snapshot=list(dict.fromkeys(tags)),
            image_url_snapshot=image_url,
            minimum_order_quantity=minimum,
            unit_code_snapshot=sku.moq_unit or product.default_unit or "piece",
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
                "minimum_order_quantity": str(minimum),
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
