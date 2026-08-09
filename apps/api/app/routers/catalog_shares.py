from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from ..catalog_share_schemas import CatalogShareCreate, CatalogShareResponse
from ..database import get_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import catalog_shares as use_cases
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
) -> CatalogShareResponse:
    context = current_context(session)
    try:
        return use_cases.create_share(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            permissions=context.permissions,
            request=request,
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
) -> CatalogShareResponse:
    try:
        return use_cases.resolve_share(session, slug=slug, token=token)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
