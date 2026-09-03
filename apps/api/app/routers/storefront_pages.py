from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..database import get_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..storefront_page_schemas import (
    MAX_STOREFRONT_HTML_BYTES,
    PublicStorefrontPageDocument,
    StorefrontCustomPageListResponse,
    StorefrontCustomPageResponse,
    StorefrontCustomPageUpdate,
)
from ..use_cases import storefront_pages as use_cases
from .errors import application_http_error

router = APIRouter(tags=["storefront-pages"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get(
    "/api/v1/storefront/pages",
    response_model=StorefrontCustomPageListResponse,
)
def list_storefront_pages(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> StorefrontCustomPageListResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return use_cases.list_pages(session, context=current_context(session))
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/storefront/pages",
    response_model=StorefrontCustomPageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_storefront_page(
    response: Response,
    title: str = Form(..., max_length=80),
    slug: str = Form(..., max_length=80),
    html_file: UploadFile = File(...),
    session: Session = Depends(get_authenticated_session),
) -> StorefrontCustomPageResponse:
    response.headers.update(NO_STORE_HEADERS)
    content = await html_file.read(MAX_STOREFRONT_HTML_BYTES + 1)
    try:
        return await run_in_threadpool(
            use_cases.create_page,
            session,
            context=current_context(session),
            title=title,
            slug=slug,
            filename=html_file.filename or "page.html",
            content=content,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    finally:
        await html_file.close()


@router.patch(
    "/api/v1/storefront/pages/{page_id}",
    response_model=StorefrontCustomPageResponse,
)
def update_storefront_page(
    page_id: UUID,
    payload: StorefrontCustomPageUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> StorefrontCustomPageResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return use_cases.update_page(
            session,
            context=current_context(session),
            page_id=page_id,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/api/v1/storefront/pages/{page_id}/html",
    response_model=StorefrontCustomPageResponse,
)
async def replace_storefront_page_html(
    page_id: UUID,
    response: Response,
    expected_version: int = Form(..., ge=1),
    html_file: UploadFile = File(...),
    session: Session = Depends(get_authenticated_session),
) -> StorefrontCustomPageResponse:
    response.headers.update(NO_STORE_HEADERS)
    content = await html_file.read(MAX_STOREFRONT_HTML_BYTES + 1)
    try:
        return await run_in_threadpool(
            use_cases.replace_page_html,
            session,
            context=current_context(session),
            page_id=page_id,
            expected_version=expected_version,
            filename=html_file.filename or "page.html",
            content=content,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    finally:
        await html_file.close()


@router.delete(
    "/api/v1/storefront/pages/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_storefront_page(
    page_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> Response:
    response.headers.update(NO_STORE_HEADERS)
    try:
        use_cases.delete_page(
            session,
            context=current_context(session),
            page_id=page_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/api/store/{tenant_slug}/pages/{page_slug}",
    response_model=PublicStorefrontPageDocument,
)
def get_public_storefront_page(
    tenant_slug: str,
    page_slug: str,
    response: Response,
    session: Session = Depends(get_session),
) -> PublicStorefrontPageDocument:
    response.headers.update({
        "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
        "X-Content-Type-Options": "nosniff",
    })
    try:
        return use_cases.public_page(
            session,
            tenant_slug=tenant_slug,
            page_slug=page_slug,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
