from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
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
from starlette.responses import StreamingResponse

from ..database import SessionLocal, get_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..services.storefront_analytics import request_visitor_ip, request_visitor_location
from ..support_schemas import (
    PublicChatConversationCreate,
    PublicChatConversationResponse,
    PublicChatMessageWrite,
    SupportConversationDetailResponse,
    SupportConversationAutomationUpdate,
    SupportConversationPageResponse,
    SupportConversationStatusUpdate,
    SupportHumanRequestSummaryResponse,
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
SUPPORT_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store, no-transform",
    "Connection": "keep-alive",
    "Content-Encoding": "identity",
    "X-Accel-Buffering": "no",
}


def _support_sse_event(event: str, payload: object) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def _support_snapshot_signature(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _support_answer_chunks(body: str, size: int | None = None) -> list[str]:
    """Split an answer into the smallest useful SSE deltas.

    The model response is currently validated as a complete JSON document before
    it can be persisted as a customer-safe message.  Once that message is ready,
    the public endpoint still needs to expose it incrementally instead of sending
    an 8+ character block at a time.  A Python string slice is Unicode-aware, so
    the default one-code-point chunks work for Chinese and other non-ASCII text;
    callers can still request larger chunks when they need to.
    """
    chunk_size = max(1, size or 1)
    return [
        body[index : index + chunk_size]
        for index in range(0, len(body), chunk_size)
    ]


def _load_public_support_snapshot(
    *,
    tenant_slug: str,
    token: str,
) -> PublicChatConversationResponse:
    with SessionLocal() as session:
        return use_cases.get_public_conversation(
            session,
            slug=tenant_slug,
            token=token,
        )


async def _public_support_event_stream(
    *,
    request: Request,
    tenant_slug: str,
    token: str,
    initial: PublicChatConversationResponse,
) -> AsyncIterator[str]:
    current = initial
    initial_payload = current.model_dump(mode="json")
    signature = _support_snapshot_signature(initial_payload)
    known_message_ids = {str(message.id) for message in current.messages}
    last_event_at = time.monotonic()
    reconnect_at = last_event_at + 50
    yield _support_sse_event("conversation", {"conversation": initial_payload})

    while time.monotonic() < reconnect_at:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.25 if current.ai_processing else 0.5)
        try:
            next_snapshot = await asyncio.to_thread(
                _load_public_support_snapshot,
                tenant_slug=tenant_slug,
                token=token,
            )
        except ApplicationError:
            yield _support_sse_event(
                "stream_error",
                {"code": "SUPPORT_STREAM_UNAVAILABLE"},
            )
            return

        next_payload = next_snapshot.model_dump(mode="json")
        next_signature = _support_snapshot_signature(next_payload)
        if next_signature != signature:
            new_ai_messages = [
                message
                for message in next_snapshot.messages
                if str(message.id) not in known_message_ids
                and message.sender_type == "AI"
            ]
            if len(new_ai_messages) == 1:
                message = new_ai_messages[0]
                message_payload = message.model_dump(mode="json")
                yield _support_sse_event(
                    "message_start",
                    {
                        "message": {
                            **message_payload,
                            "body": "",
                            "citations": [],
                        }
                    },
                )
                for delta in _support_answer_chunks(message.body):
                    if await request.is_disconnected():
                        return
                    yield _support_sse_event(
                        "message_delta",
                        {"message_id": str(message.id), "delta": delta},
                    )
                    # Keep each character visible on the client.  The browser
                    # also has a small local queue so several network chunks
                    # received in one read cannot collapse into one render.
                    await asyncio.sleep(0.018)
                yield _support_sse_event(
                    "message_end",
                    {"message": message_payload, "conversation": next_payload},
                )
            else:
                yield _support_sse_event(
                    "conversation",
                    {"conversation": next_payload},
                )
            current = next_snapshot
            signature = next_signature
            known_message_ids = {
                str(message.id) for message in next_snapshot.messages
            }
            last_event_at = time.monotonic()
        elif time.monotonic() - last_event_at >= 12:
            yield ": keep-alive\n\n"
            last_event_at = time.monotonic()


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
    "/api/v1/support/human-requests",
    response_model=SupportHumanRequestSummaryResponse,
)
def list_support_human_requests(
    response: Response,
    limit: int = Query(default=8, ge=1, le=30),
    session: Session = Depends(get_authenticated_session),
) -> SupportHumanRequestSummaryResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_human_requests(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            limit=limit,
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
            is_platform_admin=context.is_platform_admin,
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
        visitor_ip = request_visitor_ip(request)
        visitor_location = request_visitor_location(
            request,
            visitor_ip=visitor_ip,
        )
        result = use_cases.create_public_conversation(
            session,
            slug=tenant_slug,
            request=payload,
            visitor_ip=visitor_ip,
            visitor_location=visitor_location,
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


@router.get("/api/store/{tenant_slug}/support/conversations/current/events")
async def stream_public_support_conversation(
    tenant_slug: str,
    request: Request,
    x_support_token: str = Header(..., max_length=500),
) -> StreamingResponse:
    enforce_rate_limit(
        request,
        scope="public-support-conversation-stream",
        limit=configured_limit("RATE_LIMIT_PUBLIC_SUPPORT_STREAMS", 90),
        window_seconds=60,
        token=x_support_token,
    )
    try:
        initial = await asyncio.to_thread(
            _load_public_support_snapshot,
            tenant_slug=tenant_slug,
            token=x_support_token,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    return StreamingResponse(
        _public_support_event_stream(
            request=request,
            tenant_slug=tenant_slug,
            token=x_support_token,
            initial=initial,
        ),
        media_type="text/event-stream",
        headers=SUPPORT_STREAM_HEADERS,
    )


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
        visitor_ip = request_visitor_ip(request)
        visitor_location = request_visitor_location(
            request,
            visitor_ip=visitor_ip,
        )
        result = use_cases.send_public_message(
            session,
            slug=tenant_slug,
            token=x_support_token,
            request=payload,
            visitor_ip=visitor_ip,
            visitor_location=visitor_location,
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


@router.post(
    "/api/store/{tenant_slug}/support/conversations/current/human-assistance",
    response_model=PublicChatConversationResponse,
)
def request_public_human_assistance(
    tenant_slug: str,
    request: Request,
    response: Response,
    x_support_token: str = Header(..., max_length=500),
    session: Session = Depends(get_session),
) -> PublicChatConversationResponse:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="public-support-human-assistance",
        limit=configured_limit("RATE_LIMIT_PUBLIC_SUPPORT_HUMAN_REQUESTS", 10),
        window_seconds=60,
        token=x_support_token,
    )
    try:
        return use_cases.request_public_human_assistance(
            session,
            slug=tenant_slug,
            token=x_support_token,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
