from __future__ import annotations

import logging
import re
import time
from typing import Literal
from uuid import UUID
from urllib.parse import unquote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..database import get_auth_session, get_session
from ..adapters.object_storage import get_object_storage
from ..domain.errors import ApplicationError
from ..public_catalog_schemas import (
    PublicProductDetail,
    PublicExchangeRateResponse,
    PublicImageSearchResponse,
    PublicProductPage,
    PublicQuoteDraftCreate,
    PublicQuoteDraftCurrencyConversion,
    PublicQuoteDraftItemsUpdate,
    PublicQuoteDraftPriceAdjustment,
    PublicQuoteDraftItemPriceUpdate,
    PublicQuoteDraftResponse,
    PublicQuoteDraftSettingsUpdate,
    PublicQuoteDraftStatusUpdate,
    PublicQuoteDraftSummary,
    PublicSkuPage,
    PublicSkuResponse,
    PublicStoreResponse,
    StorefrontOrderStatistics,
)
from ..catalog_translation_schemas import CatalogLanguagePackResponse
from ..services.auth.dependencies import (
    bearer,
    current_context,
    get_authenticated_session,
)
from ..services.public_quote_documents import (
    fetch_remote_quote_image,
    render_public_quote_draft_pdf,
    render_public_quote_draft_xlsx,
)
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..services.storefront_analytics import (
    cleanup_expired_raw_events,
    mark_cleanup_scheduled,
    request_country_code,
    request_visitor_ip,
)
from ..use_cases import public_catalog as use_cases
from ..use_cases import catalog_translations as translation_use_cases
from ..services.language_package_storage import IMMUTABLE_CACHE_CONTROL
from .errors import application_http_error


router = APIRouter(tags=["public-catalog"])
logger = logging.getLogger(__name__)
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
PUBLIC_DETAIL_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=30, stale-while-revalidate=120",
}
PUBLIC_EXCHANGE_RATE_CACHE_HEADERS = {
    "Cache-Control": "public, max-age=300, stale-while-revalidate=900",
}
PRIVATE_DETAIL_CACHE_HEADERS = {
    # The opaque account URL changes prices and product visibility. Keep it
    # out of shared proxy caches even though visitors do not need to log in.
    "Cache-Control": "private, no-store",
}
_PUBLIC_QUOTE_MEDIA_PATTERN = re.compile(
    r"^/api/store/(?P<slug>[^/]+)/media/"
    r"(?P<image_id>[0-9a-fA-F-]{36})(?:\?[^#]*)?$"
)


def _bearer_access_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials


def _catalog_subaccount(
    identity_session: Session,
    *,
    public_session: Session,
    expected_membership_id: UUID | None,
    storefront_slug: str,
):
    # The UUID in the dedicated account URL is an opaque public storefront
    # selector, not an authenticated backend session. Private APIs still use
    # their normal bearer-token and RBAC checks.
    alias_account = use_cases.public_customer_subaccount_membership_by_storefront_slug(
        identity_session,
        storefront_slug=storefront_slug,
    )
    # Reuse this trusted exact lookup in the business repository. Opening a
    # second identity connection while this dependency holds the first can
    # exhaust the identity pool during concurrent public catalog requests.
    public_session.info.setdefault("resolved_public_storefront_aliases", {})[
        storefront_slug.casefold().strip()
    ] = alias_account[0].tenant_id if alias_account is not None else None
    if expected_membership_id is None:
        public_session.info["public_storefront_account"] = alias_account[0] if alias_account else None
        return alias_account
    explicit_account = use_cases.public_customer_subaccount_membership(
        identity_session,
        membership_id=expected_membership_id,
    )
    if alias_account is not None and alias_account[0].id != explicit_account[0].id:
        raise ApplicationError(
            "STOREFRONT_ACCOUNT_PATH_MISMATCH",
            "子账号前台路径与账号不匹配。",
            kind="not_found",
        )
    public_session.info["public_storefront_account"] = explicit_account[0]
    return explicit_account


@router.get("/api/store/{tenant_slug}", response_model=PublicStoreResponse)
def get_public_store(
    tenant_slug: str,
    response: Response,
    locale: str | None = Query(default=None, max_length=20),
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PublicStoreResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        subaccount = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        if subaccount is not None:
            response.headers.update(PRIVATE_DETAIL_CACHE_HEADERS)
        return use_cases.get_store(
            session,
            slug=tenant_slug,
            locale=locale,
            subaccount=subaccount,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/exchange-rates",
    response_model=PublicExchangeRateResponse,
)
def get_public_exchange_rates(
    tenant_slug: str,
    response: Response,
    session: Session = Depends(get_session),
) -> PublicExchangeRateResponse:
    response.headers.update(PUBLIC_EXCHANGE_RATE_CACHE_HEADERS)
    try:
        return use_cases.get_public_exchange_rates(session, slug=tenant_slug)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/language-packages/{target_locale}",
    response_model=CatalogLanguagePackResponse,
)
def get_public_language_package(
    tenant_slug: str,
    target_locale: str,
    response: Response,
    session: Session = Depends(get_session),
) -> CatalogLanguagePackResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return translation_use_cases.public_language_pack(
            session,
            slug=tenant_slug,
            target_locale=target_locale,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/language-packages/{target_locale}/versions/{version}",
)
def download_public_language_package(
    tenant_slug: str,
    target_locale: str,
    version: int,
    session: Session = Depends(get_session),
) -> Response:
    try:
        content, pack = translation_use_cases.public_language_pack_content(
            session,
            slug=tenant_slug,
            target_locale=target_locale,
            version=version,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Encoding": "gzip",
            "Cache-Control": IMMUTABLE_CACHE_CONTROL,
            "ETag": f'"{pack.content_sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/store/{tenant_slug}/skus", response_model=PublicSkuPage)
def list_public_skus(
    tenant_slug: str,
    request: Request,
    response: Response,
    q: str = Query(default="", max_length=300),
    category: str | None = Query(default=None, max_length=200),
    tags: list[str] = Query(default=[]),
    semantic: bool = Query(default=False),
    include_facets: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    locale: str | None = Query(default=None, max_length=20),
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PublicSkuPage:
    response.headers.update(NO_STORE_HEADERS)
    if locale and locale.casefold().replace("_", "-") not in {"zh", "zh-cn"}:
        enforce_rate_limit(
            request,
            scope="public-live-catalog-translation",
            limit=configured_limit("RATE_LIMIT_PUBLIC_TRANSLATION_REQUESTS", 120),
            window_seconds=configured_limit(
                "RATE_LIMIT_PUBLIC_TRANSLATION_WINDOW_SECONDS",
                60,
                maximum=86_400,
            ),
        )
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
        submitter = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        result = use_cases.list_public_skus(
            session,
            slug=tenant_slug,
            query=q,
            category=category,
            tags=tags,
            semantic=semantic,
            include_facets=include_facets,
            page=page,
            page_size=page_size,
            locale=locale,
            subaccount_membership_id=(submitter[0].id if submitter else None),
        )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/products",
    response_model=PublicProductPage,
)
def list_public_products(
    tenant_slug: str,
    request: Request,
    response: Response,
    q: str = Query(default="", max_length=300),
    category: str | None = Query(default=None, max_length=200),
    tags: list[str] = Query(default=[]),
    semantic: bool = Query(default=False),
    include_facets: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    locale: str | None = Query(default=None, max_length=20),
    share: str | None = Query(default=None, min_length=8, max_length=64),
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PublicProductPage:
    response.headers.update(NO_STORE_HEADERS)
    if locale and locale.casefold().replace("_", "-") not in {"zh", "zh-cn"}:
        enforce_rate_limit(
            request,
            scope="public-live-catalog-translation",
            limit=configured_limit(
                "RATE_LIMIT_PUBLIC_TRANSLATION_REQUESTS",
                120,
            ),
            window_seconds=configured_limit(
                "RATE_LIMIT_PUBLIC_TRANSLATION_WINDOW_SECONDS",
                60,
                maximum=86_400,
            ),
        )
    if semantic:
        enforce_rate_limit(
            request,
            scope="public-semantic-product-search",
            limit=configured_limit(
                "RATE_LIMIT_PUBLIC_AI_SEARCH_REQUESTS",
                30,
            ),
            window_seconds=configured_limit(
                "RATE_LIMIT_PUBLIC_AI_SEARCH_WINDOW_SECONDS",
                60,
                maximum=86_400,
            ),
        )
    try:
        submitter = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        result = use_cases.list_public_products(
            session,
            slug=tenant_slug,
            query=q,
            category=category,
            tags=tags,
            semantic=semantic,
            include_facets=include_facets,
            page=page,
            page_size=page_size,
            locale=locale,
            share_token=share,
            subaccount_membership_id=(submitter[0].id if submitter else None),
        )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/store/{tenant_slug}/image-search",
    response_model=PublicImageSearchResponse,
)
def search_public_products_by_image(
    tenant_slug: str,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    limit: int = Query(default=12, ge=1, le=24),
    locale: str | None = Query(default=None, max_length=20),
    share: str | None = Query(default=None, min_length=8, max_length=64),
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PublicImageSearchResponse:
    request_started = time.perf_counter()
    timings: dict[str, float] = {}
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-image-product-search",
        limit=configured_limit("RATE_LIMIT_PUBLIC_IMAGE_SEARCH_REQUESTS", 10),
        window_seconds=configured_limit(
            "RATE_LIMIT_PUBLIC_IMAGE_SEARCH_WINDOW_SECONDS",
            60,
            maximum=86_400,
        ),
    )
    max_bytes = int(
        __import__("os").getenv(
            "IMAGE_SEARCH_MAX_BYTES",
            str(20 * 1024 * 1024),
        )
    )
    content = file.file.read(max_bytes + 1)
    filename_content_type = file.content_type or "application/octet-stream"
    file.file.close()
    try:
        submitter = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        result = use_cases.search_public_products_by_image(
            session,
            slug=tenant_slug,
            content=content,
            declared_content_type=filename_content_type,
            limit=limit,
            locale=locale,
            share_token=share,
            subaccount_membership_id=(submitter[0].id if submitter else None),
            timings=timings,
        )
        timings["total"] = (time.perf_counter() - request_started) * 1000
        ordered_names = (
            "store",
            "validate",
            "provider",
            "corpus",
            "embedding",
            "vector",
            "rank",
            "catalog",
            "total",
        )
        response.headers["Server-Timing"] = ", ".join(
            f"{name};dur={timings[name]:.1f}"
            for name in ordered_names
            if name in timings
        )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/products/{product_id}",
    response_model=PublicProductDetail,
)
def get_public_product(
    tenant_slug: str,
    product_id: UUID,
    request: Request,
    response: Response,
    locale: str | None = Query(default=None, max_length=20),
    share: str | None = Query(default=None, min_length=8, max_length=64),
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PublicProductDetail:
    response.headers.update(
        PRIVATE_DETAIL_CACHE_HEADERS
        if account is not None
        else PUBLIC_DETAIL_CACHE_HEADERS
    )
    if locale and locale.casefold().replace("_", "-") not in {"zh", "zh-cn"}:
        enforce_rate_limit(
            request,
            scope="public-live-catalog-translation",
            limit=configured_limit(
                "RATE_LIMIT_PUBLIC_TRANSLATION_REQUESTS",
                120,
            ),
            window_seconds=configured_limit(
                "RATE_LIMIT_PUBLIC_TRANSLATION_WINDOW_SECONDS",
                60,
                maximum=86_400,
            ),
        )
    try:
        submitter = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        return use_cases.get_public_product(
            session,
            slug=tenant_slug,
            product_id=product_id,
            locale=locale,
            share_token=share,
            subaccount_membership_id=(submitter[0].id if submitter else None),
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
    request: Request,
    response: Response,
    locale: str | None = Query(default=None, max_length=20),
    share: str | None = Query(default=None, min_length=8, max_length=64),
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PublicSkuResponse:
    response.headers.update(NO_STORE_HEADERS)
    if locale and locale.casefold().replace("_", "-") not in {"zh", "zh-cn"}:
        enforce_rate_limit(
            request,
            scope="public-live-catalog-translation",
            limit=configured_limit("RATE_LIMIT_PUBLIC_TRANSLATION_REQUESTS", 120),
            window_seconds=configured_limit(
                "RATE_LIMIT_PUBLIC_TRANSLATION_WINDOW_SECONDS",
                60,
                maximum=86_400,
            ),
        )
    try:
        submitter = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        return use_cases.get_public_sku(
            session,
            slug=tenant_slug,
            sku_id=sku_id,
            locale=locale,
            share_token=share,
            subaccount_membership_id=(submitter[0].id if submitter else None),
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


@router.get("/api/store/{tenant_slug}/logo")
def get_public_store_logo(
    tenant_slug: str,
    session: Session = Depends(get_session),
) -> Response:
    try:
        content, content_type = use_cases.get_public_store_logo(
            session, slug=tenant_slug
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/store/{tenant_slug}/categories/{category_id}/cover")
def get_public_category_cover(
    tenant_slug: str,
    category_id: UUID,
    session: Session = Depends(get_session),
) -> Response:
    try:
        content, content_type = use_cases.get_public_category_cover(
            session,
            slug=tenant_slug,
            category_id=category_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
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
    background_tasks: BackgroundTasks,
    account: UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    identity_session: Session = Depends(get_auth_session),
    x_storefront_visitor_token: str | None = Header(default=None, max_length=500),
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
        visitor_ip = request_visitor_ip(request)
        visitor_country_code = request_country_code(
            request,
            visitor_ip=visitor_ip,
        )
        storefront_account = _catalog_subaccount(
            identity_session,
            public_session=session,
            expected_membership_id=account,
            storefront_slug=tenant_slug,
        )
        if storefront_account is not None:
            submitter = use_cases.public_customer_quote_submitter(
                identity_session,
                membership_id=storefront_account[0].id,
            )
        else:
            submitter = use_cases.optional_customer_quote_submitter(
                identity_session,
                permission_session=session,
                access_token=_bearer_access_token(credentials),
            )
        result = use_cases.create_public_quote_draft(
            session,
            slug=tenant_slug,
            request=payload,
            submitted_by_membership_id=(submitter.membership_id if submitter else None),
            submitted_by_tenant_id=(submitter.tenant_id if submitter else None),
            submitted_by_user_id=(submitter.user_id if submitter else None),
            visitor_token=x_storefront_visitor_token,
            visitor_country_code=visitor_country_code,
            visitor_ip_address=visitor_ip,
        )
        if mark_cleanup_scheduled(result.tenant_id):
            background_tasks.add_task(
                cleanup_expired_raw_events,
                result.tenant_id,
            )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/visitor/quotes",
    response_model=list[PublicQuoteDraftSummary],
)
def list_storefront_visitor_quote_drafts(
    tenant_slug: str,
    request: Request,
    response: Response,
    x_storefront_visitor_token: str = Header(..., max_length=500),
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[PublicQuoteDraftSummary]:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="storefront-visitor-quotes",
        limit=configured_limit("RATE_LIMIT_STOREFRONT_VISITOR_QUOTES", 120),
        window_seconds=60,
        token=x_storefront_visitor_token,
    )
    try:
        return use_cases.list_storefront_visitor_quote_drafts(
            session,
            slug=tenant_slug,
            visitor_token=x_storefront_visitor_token,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/api/store/{tenant_slug}/visitor/quotes/{quote_draft_id}/pdf")
def download_storefront_visitor_quote_pdf(
    tenant_slug: str,
    quote_draft_id: UUID,
    request: Request,
    x_storefront_visitor_token: str = Header(..., max_length=500),
    session: Session = Depends(get_session),
) -> Response:
    enforce_rate_limit(
        request,
        scope="storefront-visitor-quote-download-pdf",
        limit=configured_limit("RATE_LIMIT_QUOTE_DOWNLOAD_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_QUOTE_DOWNLOAD_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=x_storefront_visitor_token,
    )
    try:
        document = use_cases.get_storefront_visitor_quote_document(
            session,
            slug=tenant_slug,
            quote_draft_id=quote_draft_id,
            visitor_token=x_storefront_visitor_token,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=render_public_quote_draft_pdf(
            document,
            image_loader=_quote_image_loader(session),
        ),
        media_type="application/pdf",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="pdf"
        ),
    )


@router.get("/api/store/{tenant_slug}/visitor/quotes/{quote_draft_id}/xlsx")
def download_storefront_visitor_quote_xlsx(
    tenant_slug: str,
    quote_draft_id: UUID,
    request: Request,
    x_storefront_visitor_token: str = Header(..., max_length=500),
    session: Session = Depends(get_session),
) -> Response:
    enforce_rate_limit(
        request,
        scope="storefront-visitor-quote-download-xlsx",
        limit=configured_limit("RATE_LIMIT_QUOTE_DOWNLOAD_REQUESTS", 60),
        window_seconds=configured_limit(
            "RATE_LIMIT_QUOTE_DOWNLOAD_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=x_storefront_visitor_token,
    )
    try:
        document = use_cases.get_storefront_visitor_quote_document(
            session,
            slug=tenant_slug,
            quote_draft_id=quote_draft_id,
            visitor_token=x_storefront_visitor_token,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=_render_quote_xlsx(document, session=session),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="xlsx"
        ),
    )


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
            account_scope=context.account_scope,
            membership_id=context.membership_id,
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
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/public-quote-drafts/{quote_draft_id}/status",
    response_model=PublicQuoteDraftResponse,
)
def update_tenant_public_quote_draft_status(
    quote_draft_id: UUID,
    payload: PublicQuoteDraftStatusUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_tenant_quote_draft_status(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            request=payload,
            account_scope=context.account_scope,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/public-quote-drafts/{quote_draft_id}/settings",
    response_model=PublicQuoteDraftResponse,
)
def update_tenant_public_quote_draft_settings(
    quote_draft_id: UUID,
    payload: PublicQuoteDraftSettingsUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_tenant_quote_draft_settings(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            request=payload,
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/public-quote-drafts/{quote_draft_id}/currency-conversion",
    response_model=PublicQuoteDraftResponse,
)
def convert_tenant_public_quote_draft_currency(
    quote_draft_id: UUID,
    payload: PublicQuoteDraftCurrencyConversion,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.convert_tenant_quote_draft_currency(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            request=payload,
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/public-quote-drafts/{quote_draft_id}/items",
    response_model=PublicQuoteDraftResponse,
)
def update_tenant_public_quote_draft_items(
    quote_draft_id: UUID,
    payload: PublicQuoteDraftItemsUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_tenant_quote_draft_items(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            request=payload,
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/public-quote-drafts/{quote_draft_id}/items/price-adjustment",
    response_model=PublicQuoteDraftResponse,
)
def adjust_tenant_public_quote_draft_prices(
    quote_draft_id: UUID,
    payload: PublicQuoteDraftPriceAdjustment,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.adjust_tenant_quote_draft_prices(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            request=payload,
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/public-quote-drafts/{quote_draft_id}/items/{item_id}/price",
    response_model=PublicQuoteDraftResponse,
)
def update_tenant_public_quote_draft_item_price(
    quote_draft_id: UUID,
    item_id: UUID,
    payload: PublicQuoteDraftItemPriceUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_tenant_quote_draft_item_price(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            item_id=item_id,
            request=payload,
            sync_to_catalog=False,
            account_scope=context.account_scope,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/public-quote-drafts/{quote_draft_id}/items/{item_id}/sync-price",
    response_model=PublicQuoteDraftResponse,
)
def sync_tenant_public_quote_draft_item_price(
    quote_draft_id: UUID,
    item_id: UUID,
    payload: PublicQuoteDraftItemPriceUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> PublicQuoteDraftResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_tenant_quote_draft_item_price(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            quote_draft_id=quote_draft_id,
            item_id=item_id,
            request=payload,
            sync_to_catalog=True,
            account_scope=context.account_scope,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/storefront-orders/statistics",
    response_model=StorefrontOrderStatistics,
)
def get_tenant_storefront_order_statistics(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> StorefrontOrderStatistics:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_tenant_order_statistics(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


def _document_headers(*, quote_number: str, extension: str) -> dict[str, str]:
    disposition = "inline" if extension == "pdf" else "attachment"
    return {
        "Content-Disposition": f'{disposition}; filename="{quote_number}.{extension}"',
        "Cache-Control": "private, no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


def _quote_image_loader(session: Session):
    cache: dict[str, bytes | None] = {}

    def load(image_url: str) -> bytes | None:
        if image_url in cache:
            return cache[image_url]
        content: bytes | None = None
        match = _PUBLIC_QUOTE_MEDIA_PATTERN.fullmatch(image_url)
        try:
            if match is not None:
                content, _content_type = use_cases.get_public_media(
                    session,
                    slug=unquote(match.group("slug")),
                    image_id=UUID(match.group("image_id")),
                )
            elif image_url.startswith(("https://", "http://")):
                content = fetch_remote_quote_image(image_url)
        except Exception:
            logger.info(
                "quote image could not be embedded",
                extra={"image_url": image_url[:500]},
            )
        cache[image_url] = content
        return content

    return load


def _render_quote_xlsx(
    document,
    *,
    session: Session,
    document_type: Literal["quotation", "proforma_invoice", "packing_list"] = "quotation",
) -> bytes:
    image_loader = _quote_image_loader(session)
    template = document.excel_template
    if document_type == "quotation" and template is not None:
        try:
            with get_object_storage().materialize(template.object_key) as path:
                return render_public_quote_draft_xlsx(
                    document,
                    template_path=path,
                    image_loader=image_loader,
                    document_type=document_type,
                )
        except Exception:
            logger.exception(
                "custom quote Excel rendering failed; using the standard template",
                extra={"quote_number": document.quote.quote_number},
            )
    return render_public_quote_draft_xlsx(
        document,
        image_loader=image_loader,
        document_type=document_type,
    )


def _document_number(
    document,
    document_type: Literal["quotation", "proforma_invoice", "packing_list"],
) -> str:
    if document_type == "packing_list" and document.quote.packing_list is not None:
        return document.quote.packing_list.packing_list_number
    if document_type == "proforma_invoice":
        settings = document.quote.proforma_invoice
        if settings is not None and settings.invoice_number:
            return settings.invoice_number
    return document.quote.quote_number


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
        content=render_public_quote_draft_pdf(
            document,
            image_loader=_quote_image_loader(session),
        ),
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
        content=_render_quote_xlsx(document, session=session),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_document_headers(
            quote_number=document.quote.quote_number, extension="xlsx"
        ),
    )


@router.get("/api/v1/public-quote-drafts/{quote_draft_id}/pdf")
def download_tenant_quote_draft_pdf(
    quote_draft_id: UUID,
    request: Request,
    document_type: Literal["quotation", "proforma_invoice", "packing_list"] = Query("quotation"),
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
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=render_public_quote_draft_pdf(
            document,
            image_loader=_quote_image_loader(session),
            document_type=document_type,
        ),
        media_type="application/pdf",
        headers=_document_headers(
            quote_number=_document_number(document, document_type), extension="pdf"
        ),
    )


@router.get("/api/v1/public-quote-drafts/{quote_draft_id}/xlsx")
def download_tenant_quote_draft_xlsx(
    quote_draft_id: UUID,
    request: Request,
    document_type: Literal["quotation", "proforma_invoice", "packing_list"] = Query("quotation"),
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
            account_scope=context.account_scope,
            membership_id=context.membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=_render_quote_xlsx(
            document,
            session=session,
            document_type=document_type,
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_document_headers(
            quote_number=_document_number(document, document_type), extension="xlsx"
        ),
    )
