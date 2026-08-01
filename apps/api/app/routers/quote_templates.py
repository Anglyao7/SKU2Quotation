from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..quote_template_schemas import (
    QuoteExcelTemplateListResponse,
    QuoteExcelTemplateReparseRequest,
    QuoteExcelTemplateResponse,
    QuoteExcelTemplateUpdateRequest,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import quote_templates as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/quote-excel-templates", tags=["quote-templates"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("", response_model=QuoteExcelTemplateListResponse)
def list_quote_excel_templates(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> QuoteExcelTemplateListResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_templates(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "",
    response_model=QuoteExcelTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_quote_excel_template(
    response: Response,
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=160),
    session: Session = Depends(get_authenticated_session),
) -> QuoteExcelTemplateResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return await use_cases.upload_template(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            permissions=context.permissions,
            upload=file,
            name=name,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/{template_id}/reparse", response_model=QuoteExcelTemplateResponse)
def reparse_quote_excel_template(
    template_id: UUID,
    payload: QuoteExcelTemplateReparseRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> QuoteExcelTemplateResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.reparse_template(
            session,
            tenant_id=context.tenant_id,
            template_id=template_id,
            user_id=context.user_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put("/{template_id}", response_model=QuoteExcelTemplateResponse)
def update_quote_excel_template(
    template_id: UUID,
    payload: QuoteExcelTemplateUpdateRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> QuoteExcelTemplateResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_template(
            session,
            tenant_id=context.tenant_id,
            template_id=template_id,
            user_id=context.user_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quote_excel_template(
    template_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> Response:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        use_cases.delete_template(
            session,
            tenant_id=context.tenant_id,
            template_id=template_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
