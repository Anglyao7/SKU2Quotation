from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..system_schemas import OutboxMetricsResponse, SystemMonitoringResponse
from ..image_generation_schemas import (
    ImageGenerationSettingsResponse,
    ImageGenerationSettingsUpdateRequest,
)
from ..translation_management_schemas import (
    TranslationSettingsResponse,
    TranslationSettingsTestRequest,
    TranslationSettingsTestResponse,
    TranslationSettingsUpdateRequest,
)
from ..use_cases import image_generation, system_operations, translation_management
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/system", tags=["system"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get(
    "/image-generation/settings",
    response_model=ImageGenerationSettingsResponse,
)
def get_image_generation_settings(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageGenerationSettingsResponse:
    context = current_context(session)
    response.headers.update(NO_STORE_HEADERS)
    try:
        return image_generation.get_settings(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/image-generation/settings",
    response_model=ImageGenerationSettingsResponse,
)
def update_image_generation_settings(
    payload: ImageGenerationSettingsUpdateRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> ImageGenerationSettingsResponse:
    context = current_context(session)
    response.headers.update(NO_STORE_HEADERS)
    try:
        return image_generation.update_settings(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/translation/settings",
    response_model=TranslationSettingsResponse,
)
def get_translation_settings(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> TranslationSettingsResponse:
    context = current_context(session)
    response.headers.update(NO_STORE_HEADERS)
    try:
        return translation_management.get_settings(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/translation/settings",
    response_model=TranslationSettingsResponse,
)
def update_translation_settings(
    payload: TranslationSettingsUpdateRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> TranslationSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return translation_management.update_settings(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/translation/settings/test",
    response_model=TranslationSettingsTestResponse,
)
def test_translation_settings(
    payload: TranslationSettingsTestRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> TranslationSettingsTestResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return translation_management.test_settings(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/metrics", response_model=SystemMonitoringResponse)
def system_metrics(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SystemMonitoringResponse:
    context = current_context(session)
    response.headers["Cache-Control"] = "no-store"
    try:
        return system_operations.get_system_monitoring(context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/outbox/metrics", response_model=OutboxMetricsResponse)
def outbox_metrics(
    session: Session = Depends(get_authenticated_session),
) -> OutboxMetricsResponse:
    context = current_context(session)
    try:
        return system_operations.get_outbox_metrics(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
