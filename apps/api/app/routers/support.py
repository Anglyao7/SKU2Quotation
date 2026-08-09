from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from ..database import get_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..support_schemas import (
    PublicChatConversationCreate,
    PublicChatConversationResponse,
    PublicChatMessageWrite,
    SupportConversationDetailResponse,
    SupportConversationAutomationUpdate,
    SupportConversationPageResponse,
    SupportConversationStatusUpdate,
    SupportMerchantMessageWrite,
    SupportSettingsResponse,
    SupportSettingsUpdate,
    SupportTranslationPreviewResponse,
    SupportTranslationPreviewWrite,
)
from ..use_cases import support as use_cases
from ..services.support_ai_orchestrator import (
    process_queued_runs_for_public_conversation,
)
from ..services.support_ai_configuration import support_ai_inline_processing_enabled
from .errors import application_http_error


router = APIRouter(tags=["storefront-support"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("/api/v1/support/settings", response_model=SupportSettingsResponse)
def get_support_settings(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_settings(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/api/v1/support/settings", response_model=SupportSettingsResponse)
def update_support_settings(
    payload: SupportSettingsUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_settings(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/settings/actions/{slot}/image",
    response_model=SupportSettingsResponse,
)
async def upload_support_action_image(
    slot: int = Path(ge=2, le=3),
    image: UploadFile = File(...),
    session: Session = Depends(get_authenticated_session),
) -> SupportSettingsResponse:
    context = current_context(session)
    content = await image.read(use_cases.MAX_ACTION_IMAGE_BYTES + 1)
    try:
        return use_cases.upload_action_image(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            permissions=context.permissions,
            slot=slot,
            filename=image.filename,
            declared_media_type=image.content_type,
            content=content,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/conversations",
    response_model=SupportConversationPageResponse,
)
def list_support_conversations(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    conversation_status: Literal["OPEN", "CLOSED"] | None = Query(
        default=None,
        alias="status",
    ),
    q: str = Query(default="", max_length=200),
    session: Session = Depends(get_authenticated_session),
) -> SupportConversationPageResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_conversations(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            page=page,
            page_size=page_size,
            status=conversation_status,
            query=q,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/conversations/{conversation_id}",
    response_model=SupportConversationDetailResponse,
)
def get_support_conversation(
    conversation_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportConversationDetailResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_conversation(
            session,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/conversations/{conversation_id}/messages",
    response_model=SupportConversationDetailResponse,
)
def reply_support_conversation(
    conversation_id: UUID,
    payload: SupportMerchantMessageWrite,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportConversationDetailResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.send_merchant_message(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            conversation_id=conversation_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/conversations/{conversation_id}/translation-preview",
    response_model=SupportTranslationPreviewResponse,
)
def preview_support_reply_translation(
    conversation_id: UUID,
    payload: SupportTranslationPreviewWrite,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportTranslationPreviewResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.preview_merchant_message_translation(
            session,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/support/conversations/{conversation_id}",
    response_model=SupportConversationDetailResponse,
)
def update_support_conversation(
    conversation_id: UUID,
    payload: SupportConversationStatusUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportConversationDetailResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_conversation_status(
            session,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/support/conversations/{conversation_id}/automation",
    response_model=SupportConversationDetailResponse,
)
def update_support_conversation_automation(
    conversation_id: UUID,
    payload: SupportConversationAutomationUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportConversationDetailResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_conversation_automation(
            session,
            tenant_id=context.tenant_id,
            conversation_id=conversation_id,
            permissions=context.permissions,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/api/store/{tenant_slug}/support/actions/{slot}/image")
def get_support_action_image(
    tenant_slug: str,
    slot: int = Path(ge=2, le=3),
    session: Session = Depends(get_session),
) -> Response:
    try:
        content, media_type = use_cases.get_public_action_image(
            session,
            slug=tenant_slug,
            slot=slot,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/api/store/{tenant_slug}/support/conversations",
    response_model=PublicChatConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_public_support_conversation(
    tenant_slug: str,
    payload: PublicChatConversationCreate,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> PublicChatConversationResponse:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-support-conversation-create",
        limit=configured_limit("RATE_LIMIT_PUBLIC_SUPPORT_CREATES", 12),
        window_seconds=configured_limit(
            "RATE_LIMIT_PUBLIC_SUPPORT_CREATE_WINDOW_SECONDS",
            600,
            maximum=86_400,
        ),
    )
    try:
        result = use_cases.create_public_conversation(
            session,
            slug=tenant_slug,
            request=payload,
        )
        if result.ai_processing and support_ai_inline_processing_enabled():
            background_tasks.add_task(
                process_queued_runs_for_public_conversation,
                tenant_slug=tenant_slug,
                conversation_id=result.id,
            )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/store/{tenant_slug}/support/conversations/current",
    response_model=PublicChatConversationResponse,
)
def get_public_support_conversation(
    tenant_slug: str,
    response: Response,
    x_support_token: str = Header(..., max_length=500),
    session: Session = Depends(get_session),
) -> PublicChatConversationResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return use_cases.get_public_conversation(
            session,
            slug=tenant_slug,
            token=x_support_token,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/store/{tenant_slug}/support/conversations/current/messages",
    response_model=PublicChatConversationResponse,
)
def send_public_support_message(
    tenant_slug: str,
    payload: PublicChatMessageWrite,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    x_support_token: str = Header(..., max_length=500),
    session: Session = Depends(get_session),
) -> PublicChatConversationResponse:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-support-message-send",
        limit=configured_limit("RATE_LIMIT_PUBLIC_SUPPORT_MESSAGES", 60),
        window_seconds=60,
        token=x_support_token,
    )
    try:
        result = use_cases.send_public_message(
            session,
            slug=tenant_slug,
            token=x_support_token,
            request=payload,
        )
        if result.ai_processing and support_ai_inline_processing_enabled():
            background_tasks.add_task(
                process_queued_runs_for_public_conversation,
                tenant_slug=tenant_slug,
                conversation_id=result.id,
            )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
