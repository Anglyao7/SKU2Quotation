from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..announcement_schemas import (
    AnnouncementListResponse,
    AnnouncementResponse,
    AnnouncementWriteRequest,
)
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import announcements as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/announcements", tags=["announcements"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("", response_model=AnnouncementListResponse)
def list_announcements(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> AnnouncementListResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_announcements(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_announcement(
    payload: AnnouncementWriteRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> AnnouncementResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.create_announcement(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: UUID,
    payload: AnnouncementWriteRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> AnnouncementResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_announcement(
            session,
            tenant_id=context.tenant_id,
            announcement_id=announcement_id,
            user_id=context.user_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/{announcement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_announcement(
    announcement_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> Response:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        use_cases.delete_announcement(
            session,
            tenant_id=context.tenant_id,
            announcement_id=announcement_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
