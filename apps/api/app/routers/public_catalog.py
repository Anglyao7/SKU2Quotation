from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session

from ..database import get_session
from ..domain.errors import ApplicationError
from ..public_catalog_schemas import (
    PublicQuoteDraftCreate,
    PublicQuoteDraftResponse,
    PublicQuoteDraftSummary,
    PublicSkuPage,
    PublicSkuResponse,
    PublicStoreResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.public_quote_documents import (
    render_public_quote_draft_pdf,
    render_public_quote_draft_xlsx,
)
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import public_catalog as use_cases
from .errors import application_http_error


router = APIRouter(tags=["public-catalog"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("/api/store/{tenant_slug}", response_model=PublicStoreResponse)
def get_public_store(
    tenant_slug: str,
    session: Session = Depends(get_session),
) -> PublicStoreResponse:
    try:
        return use_cases.get_store(session, slug=tenant_slug)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/api/store/{tenant_slug}/skus", response_model=PublicSkuPage)
def list_public_skus(
    tenant_slug: str,
    request: Request,
    q: str = Query(default="", max_length=300),
    category: str | None = Query(default=None, max_length=200),
    tags: list[str] = Query(default=[]),
    semantic: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    session: Session = Depends(get_session),
) -> PublicSkuPage:
    if semantic:
        enforce_rate_limit(
            request,
            scope="public-semantic-product-search",
            limit=configured_limit("RATE_LIMIT_PUBLIC_AI_SEARCH_REQUESTS", 30),
            window_seconds=configured_limit(
                "RATE_LIMIT_PUBLIC_AI_SEARCH_WINDOW_SECONDS",
                60,
                maximum=86_400,
            ),
        )
    try:
        return use_cases.list_public_skus(
            session,
            slug=tenant_slug,
            query=q,
            category=category,
            tags=tags,
            semantic=semantic,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/skus/{sku_id}",
    response_model=PublicSkuResponse,
)
def get_public_sku(
    tenant_slug: str,
    sku_id: UUID,
    session: Session = Depends(get_session),
) -> PublicSkuResponse:
    try:
        return use_cases.get_public_sku(
            session,
            slug=tenant_slug,
            sku_id=sku_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/api/store/{tenant_slug}/media/{image_id}")
def get_public_media(
    tenant_slug: str,
    image_id: UUID,
    session: Session = Depends(get_session),
) -> Response:
    try:
        content, content_type = use_cases.get_public_media(
            session, slug=tenant_slug, image_id=image_id
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/api/store/{tenant_slug}/quotes",
    response_model=PublicQuoteDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_public_quote_draft(
    tenant_slug: str,
    payload: PublicQuoteDraftCreate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-quote-create",
        limit=configured_limit("RATE_LIMIT_PUBLIC_QUOTE_REQUESTS", 20),
        window_seconds=configured_limit(
            "RATE_LIMIT_PUBLIC_QUOTE_WINDOW_SECONDS", 3_600, maximum=86_400
        ),
    )
    try:
        return use_cases.create_public_quote_draft(
            session, slug=tenant_slug, request=payload
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/public-quote-drafts", response_model=list[PublicQuoteDraftSummary]
)
def list_tenant_public_quote_drafts(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_authenticated_session),
) -> list[PublicQuoteDraftSummary]:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_tenant_quote_drafts(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/public-quote-drafts/{quote_draft_id}",
    response_model=PublicQuoteDraftResponse,
)
def get_tenant_public_quote_draft(
    quote_draft_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_tenant_quote_draft(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


def _document_headers(*, quote_number: str, extension: str) -> dict[str, str]:
    disposition = "inline" if extension == "pdf" else "attachment"
    return {
        "Content-Disposition": (
            f'{disposition}; filename="{quote_number}-PENDING-CONFIRMATION.{extension}"'
        ),
        "Cache-Control": "private, no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Quote-Status": "PENDING_CONFIRMATION",
    }


@router.get("/api/quotes/{quote_draft_id}/pdf")
def download_public_quote_draft_pdf(
    quote_draft_id: UUID,
    request: Request,
    token: str = Header(
        alias="X-Quote-Download-Token", min_length=40, max_length=256
    ),
    session: Session = Depends(get_session),
) -> Response:
    enforce_rate_limit(
        request,
        scope="public-quote-download-pdf",
        limit=configured_limit("RATE_LIMIT_QUOTE_DOWNLOAD_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_QUOTE_DOWNLOAD_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=token,
    )
    try:
        document = use_cases.get_quote_document(
            session, quote_draft_id=quote_draft_id, raw_token=token
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=render_public_quote_draft_pdf(document),
        media_type="application/pdf",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="pdf"
        ),
    )


@router.get("/api/quotes/{quote_draft_id}/xlsx")
def download_public_quote_draft_xlsx(
    quote_draft_id: UUID,
    request: Request,
    token: str = Header(
        alias="X-Quote-Download-Token", min_length=40, max_length=256
    ),
    session: Session = Depends(get_session),
) -> Response:
    enforce_rate_limit(
        request,
        scope="public-quote-download-xlsx",
        limit=configured_limit("RATE_LIMIT_QUOTE_DOWNLOAD_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_QUOTE_DOWNLOAD_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=token,
    )
    try:
        document = use_cases.get_quote_document(
            session, quote_draft_id=quote_draft_id, raw_token=token
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=render_public_quote_draft_xlsx(document),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="xlsx"
        ),
    )


@router.get("/api/v1/public-quote-drafts/{quote_draft_id}/pdf")
def download_tenant_quote_draft_pdf(
    quote_draft_id: UUID,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> Response:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="tenant-quote-download-pdf",
        limit=configured_limit("RATE_LIMIT_QUOTE_DOWNLOAD_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_QUOTE_DOWNLOAD_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        document = use_cases.get_tenant_quote_document(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=render_public_quote_draft_pdf(document),
        media_type="application/pdf",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="pdf"
        ),
    )


@router.get("/api/v1/public-quote-drafts/{quote_draft_id}/xlsx")
def download_tenant_quote_draft_xlsx(
    quote_draft_id: UUID,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> Response:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="tenant-quote-download-xlsx",
        limit=configured_limit("RATE_LIMIT_QUOTE_DOWNLOAD_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_QUOTE_DOWNLOAD_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        document = use_cases.get_tenant_quote_document(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=render_public_quote_draft_xlsx(document),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="xlsx"
        ),
    )
