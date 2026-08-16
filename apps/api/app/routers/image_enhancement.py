from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..image_enhancement_schemas import (
    ImageEnhancementCancelRequest,
    ImageEnhancementConfirmRequest,
    ImageEnhancementReviewRequest,
    ImageEnhancementStartRequest,
    ImageEnhancementTaskResponse,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import image_enhancement
from .errors import application_http_error


router = APIRouter(
    prefix="/api/v1/product-center/image-enhancements",
    tags=["product-image-enhancement"],
)
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.post("", response_model=ImageEnhancementTaskResponse, status_code=202)
def start_image_enhancement(
    payload: ImageEnhancementStartRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEnhancementTaskResponse:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="product-image-enhancement",
        limit=configured_limit("RATE_LIMIT_IMAGE_ENHANCEMENT_TASKS", 20),
        window_seconds=configured_limit(
            "RATE_LIMIT_IMAGE_ENHANCEMENT_WINDOW_SECONDS", 3600, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return image_enhancement.start_task(
            session,
            context=current_context(session),
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc

@router.get("", response_model=list[ImageEnhancementTaskResponse])
def list_image_enhancement_tasks(
    response: Response,
    limit: int = 20,
    session: Session = Depends(get_authenticated_session),
) -> list[ImageEnhancementTaskResponse]:
    response.headers.update(NO_STORE_HEADERS)
    try:
        context = current_context(session)
        return image_enhancement.list_tasks(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            limit=limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/{task_id}", response_model=ImageEnhancementTaskResponse)
def get_image_enhancement_task(
    task_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEnhancementTaskResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        context = current_context(session)
        return image_enhancement.get_task(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            task_id=task_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/{task_id}/cancel", response_model=ImageEnhancementTaskResponse)
def cancel_image_enhancement_task(
    task_id: UUID,
    payload: ImageEnhancementCancelRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEnhancementTaskResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return image_enhancement.cancel_task(
            session,
            context=current_context(session),
            task_id=task_id,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/{task_id}/review", response_model=ImageEnhancementTaskResponse)
def review_image_enhancement_task(
    task_id: UUID,
    payload: ImageEnhancementReviewRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEnhancementTaskResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return image_enhancement.review_task(
            session,
            context=current_context(session),
            task_id=task_id,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post("/{task_id}/confirm", response_model=ImageEnhancementTaskResponse)
def confirm_image_enhancement_task(
    task_id: UUID,
    payload: ImageEnhancementConfirmRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageEnhancementTaskResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return image_enhancement.confirm_task(
            session,
            context=current_context(session),
            task_id=task_id,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
