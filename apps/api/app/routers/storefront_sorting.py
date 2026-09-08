from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services import storefront_sorting
from .errors import application_http_error

router = APIRouter(prefix="/api/v1/storefront/sorting", tags=["storefront-sorting"])


class CategoryPriorityUpdate(BaseModel):
    priority_category_ids: list[UUID] = Field(max_length=100)


@router.get("")
def settings(response: Response, session: Session = Depends(get_authenticated_session)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return storefront_sorting.editor_settings(session, current_context(session))
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("")
def update(payload: CategoryPriorityUpdate, response: Response, session: Session = Depends(get_authenticated_session)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return storefront_sorting.update_categories(session, current_context(session), payload.priority_category_ids)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/products")
def products(response: Response, q: str = Query(default="", max_length=200), page: int = Query(default=1, ge=1),
             page_size: int = Query(default=20, ge=1, le=100), session: Session = Depends(get_authenticated_session)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return storefront_sorting.editor_products(session, current_context(session), query=q, page=page, page_size=page_size)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
