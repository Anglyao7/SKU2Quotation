from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..catalog_share_schemas import CatalogShareCreate, CatalogShareResponse
from ..database import get_auth_session, get_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import catalog_shares as use_cases
from ..use_cases import public_catalog
from ..services.catalog_share_metadata import share_html, placeholder_image
from ..services.rate_limit import enforce_rate_limit
from .public_catalog import _catalog_subaccount
from .errors import application_http_error


router = APIRouter(tags=["catalog-shares"])


@router.post(
    "/api/v1/catalog-shares",
    response_model=CatalogShareResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_catalog_share(
    request: CatalogShareCreate,
    session: Session = Depends(get_authenticated_session),
    identity_session: Session = Depends(get_auth_session),
) -> CatalogShareResponse:
    context = current_context(session)
    try:
        subaccount = (
            public_catalog.public_customer_subaccount_membership(identity_session, membership_id=context.membership_id)
            if context.account_scope == "CUSTOMER_SUBACCOUNT" else None
        )
        return use_cases.create_share(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            permissions=context.permissions,
            request=request,
            subaccount=subaccount,
        )
    except ApplicationError as exc:
        session.rollback()
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{slug}/shares/{token}",
    response_model=CatalogShareResponse,
)
def get_catalog_share(
    slug: str,
    token: str = Path(min_length=8, max_length=64),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> CatalogShareResponse:
    try:
        subaccount = _catalog_subaccount(identity_session, public_session=session, expected_membership_id=None, storefront_slug=slug)
        return use_cases.resolve_share(session, slug=slug, token=token, subaccount=subaccount)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/api/catalog-share-navigation.js", include_in_schema=False)
def share_navigation() -> Response:
    # External script works with production's script-src 'self' CSP. Crawlers
    # see metadata in the original HTML; browsers enter the normal SPA view.
    return Response(
        "const link = document.querySelector('a[data-share-target]');"
        "if (link && new URL(link.href).origin === location.origin) location.replace(link.href);",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/catalog-share-placeholder.png", include_in_schema=False)
def share_placeholder() -> Response:
    return Response(placeholder_image(), media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.api_route("/api/store/{slug}/shares/{token}/preview", methods=["GET", "HEAD"], response_class=HTMLResponse)
def get_share_preview(
    request: Request,
    slug: str,
    token: str = Path(min_length=8, max_length=64),
    lang: str | None = Query(default=None, max_length=20),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> Response:
    enforce_rate_limit(request, scope="catalog-share-preview", limit=120, window_seconds=60)
    try:
        subaccount = _catalog_subaccount(identity_session, public_session=session, expected_membership_id=None, storefront_slug=slug)
        share = use_cases.resolve_share(session, slug=slug, token=token, subaccount=subaccount)
        page = public_catalog.list_public_products(
            session, slug=slug, query="", category=None, tags=[], semantic=False,
            include_facets=False, page=1, page_size=4, locale=lang, share_token=token,
            subaccount_membership_id=subaccount[0].id if subaccount is not None else None,
        )
        if not page.items:
            raise ApplicationError("CATALOG_SHARE_NOT_FOUND", "分享内容不存在或已失效。", kind="not_found")
        return HTMLResponse(share_html(share, page, origin=str(request.base_url)), headers={"Cache-Control": "no-store"})
    except ApplicationError:
        # No stale product titles or parent branding for removed/private items.
        return HTMLResponse('<!doctype html><html><head><meta name="robots" content="noindex"><title>Share unavailable</title></head><body>Share unavailable</body></html>', status_code=404, headers={"Cache-Control": "no-store"})
