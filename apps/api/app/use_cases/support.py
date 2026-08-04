from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
from ..file_security_models import MediaObjectRow
from ..model_mixins import utcnow
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import public_catalog_repository
from ..repositories import support_repository as repository
from ..services.auth.tokens import hash_secret, new_secret
from ..support_models import (
    StorefrontChatConversationRow,
    StorefrontChatMessageRow,
)
from ..support_schemas import (
    PublicChatConversationCreate,
    PublicChatConversationResponse,
    PublicChatMessageWrite,
    PublicSupportWidgetResponse,
    SupportChatMessageResponse,
    SupportConversationDetailResponse,
    SupportConversationPageResponse,
    SupportConversationStatusUpdate,
    SupportConversationSummaryResponse,
    SupportCustomActionResponse,
    SupportMerchantMessageWrite,
    SupportSettingsResponse,
    SupportSettingsUpdate,
)


DEFAULT_WELCOME_MESSAGE = "您好，请告诉我们您正在寻找什么商品，我们会尽快回复。"
MAX_ACTION_IMAGE_BYTES = 5 * 1024 * 1024


def _require(permissions: frozenset[str], permission: str) -> None:
    if permission not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {permission}",
            kind="forbidden",
        )


def _profile(session: Session, *, tenant_id: UUID) -> TenantPublicProfileRow:
    profile = public_catalog_repository.find_profile_by_tenant(
        session,
        tenant_id=tenant_id,
    )
    if profile is None:
        raise ApplicationError(
            "SUPPORT_SETTINGS_UNAVAILABLE",
            "当前商家尚未创建商品前台配置。",
            kind="not_found",
        )
    return profile


def _stored_actions(profile: TenantPublicProfileRow) -> dict[int, dict[str, Any]]:
    raw = profile.support_widget_config or {}
    result: dict[int, dict[str, Any]] = {}
    for value in raw.get("custom_actions", []) if isinstance(raw, dict) else []:
        if not isinstance(value, dict):
            continue
        try:
            slot = int(value.get("slot"))
        except (TypeError, ValueError):
            continue
        if slot in {2, 3}:
            result[slot] = value
    return result


def _image_path(slug: str, slot: int, media_id: str) -> str:
    return (
        f"/api/store/{quote(slug, safe='')}/support/actions/{slot}/image"
        f"?v={quote(media_id, safe='')}"
    )


def _action_response(
    *,
    slug: str,
    slot: int,
    value: dict[str, Any] | None,
) -> SupportCustomActionResponse:
    item = value or {}
    external = str(item.get("external_image_url") or "").strip() or None
    media_id = str(item.get("image_media_id") or "").strip() or None
    return SupportCustomActionResponse(
        slot=slot,
        visible=bool(item.get("visible", False)),
        label=str(item.get("label") or "").strip() or None,
        target_url=str(item.get("target_url") or "").strip() or None,
        external_image_url=external,
        image_url=(external or (_image_path(slug, slot, media_id) if media_id else None)),
        has_uploaded_image=bool(media_id),
    )


def settings_response(profile: TenantPublicProfileRow) -> SupportSettingsResponse:
    config = profile.support_widget_config or {}
    actions = _stored_actions(profile)
    welcome = (
        str(config.get("welcome_message") or "").strip()
        if isinstance(config, dict)
        else ""
    )
    return SupportSettingsResponse(
        welcome_message=welcome or DEFAULT_WELCOME_MESSAGE,
        custom_actions=[
            _action_response(slug=profile.slug, slot=slot, value=actions.get(slot))
            for slot in (2, 3)
        ],
    )


def get_settings(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> SupportSettingsResponse:
    _require(permissions, "support.settings_manage")
    return settings_response(_profile(session, tenant_id=tenant_id))


def update_settings(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: SupportSettingsUpdate,
) -> SupportSettingsResponse:
    _require(permissions, "support.settings_manage")
    profile = _profile(session, tenant_id=tenant_id)
    existing = _stored_actions(profile)
    requested = {item.slot: item for item in request.custom_actions}
    stored: list[dict[str, Any]] = []
    for slot in (2, 3):
        item = requested.get(slot)
        previous = existing.get(slot, {})
        if item is None:
            stored.append({"slot": slot, **previous})
            continue
        if item.visible and not item.target_url:
            raise ApplicationError(
                "SUPPORT_ACTION_TARGET_REQUIRED",
                f"请为第 {slot} 个悬浮球填写跳转链接。",
            )
        if item.visible and not (
            item.external_image_url or previous.get("image_media_id")
        ):
            raise ApplicationError(
                "SUPPORT_ACTION_IMAGE_REQUIRED",
                f"请为第 {slot} 个悬浮球上传或填写图片。",
            )
        stored.append(
            {
                "slot": slot,
                "visible": item.visible,
                "label": item.label,
                "target_url": item.target_url,
                "external_image_url": item.external_image_url,
                "image_media_id": previous.get("image_media_id"),
            }
        )
    profile.support_widget_config = {
        "welcome_message": request.welcome_message,
        "custom_actions": stored,
    }
    session.commit()
    session.refresh(profile)
    return settings_response(profile)


def upload_action_image(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    slot: int,
    filename: str | None,
    declared_media_type: str | None,
    content: bytes,
) -> SupportSettingsResponse:
    _require(permissions, "support.settings_manage")
    if slot not in {2, 3}:
        raise ApplicationError("SUPPORT_ACTION_SLOT_INVALID", "悬浮球位置无效。")
    if not content:
        raise ApplicationError("SUPPORT_IMAGE_EMPTY", "请选择一张图片。")
    if len(content) > MAX_ACTION_IMAGE_BYTES:
        raise ApplicationError(
            "SUPPORT_IMAGE_TOO_LARGE",
            "悬浮球图片不能超过 5 MB。",
            kind="too_large",
        )
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            has_alpha = "A" in image.getbands()
            normalized = image.convert("RGBA" if has_alpha else "RGB")
            output = io.BytesIO()
            normalized.save(output, format="WEBP", quality=90, method=4)
            processed = output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ApplicationError(
            "SUPPORT_IMAGE_INVALID",
            "图片无法识别，请上传 PNG、JPG 或 WebP 文件。",
        ) from exc
    profile = _profile(session, tenant_id=tenant_id)
    media_id = uuid4()
    object_key = f"tenants/{tenant_id}/support/actions/{media_id}.webp"
    with tempfile.NamedTemporaryFile(suffix=".webp") as temporary:
        temporary.write(processed)
        temporary.flush()
        get_object_storage().put_file(
            Path(temporary.name),
            object_key=object_key,
            content_type="image/webp",
        )
    media = MediaObjectRow(
        id=media_id,
        tenant_id=tenant_id,
        object_key=object_key,
        zone="APPROVED_MEDIA",
        original_filename=(filename or f"support-action-{slot}.webp")[:500],
        sha256=hashlib.sha256(processed).hexdigest(),
        byte_size=len(processed),
        declared_media_type=declared_media_type,
        detected_media_type="image/webp",
        status="AVAILABLE",
        scan_status="CLEAN",
        scan_engine="pillow-reencode",
        scan_result={"normalized": True},
        scan_at=utcnow(),
        retention_class="SOURCE_DEFAULT",
        created_by_user_id=user_id,
    )
    session.add(media)
    actions = _stored_actions(profile)
    current = dict(actions.get(slot, {}))
    current.update({"slot": slot, "image_media_id": str(media_id)})
    actions[slot] = current
    config = dict(profile.support_widget_config or {})
    config["custom_actions"] = [actions.get(value, {"slot": value}) for value in (2, 3)]
    profile.support_widget_config = config
    session.commit()
    session.refresh(profile)
    return settings_response(profile)


def _resolve_public_store(
    session: Session,
    *,
    slug: str,
) -> tuple[object, TenantPublicProfileRow]:
    profile = public_catalog_repository.find_published_profile_by_slug(
        session,
        slug=slug.casefold().strip(),
    )
    if profile is None:
        raise ApplicationError("STORE_NOT_FOUND", "Store was not found.", kind="not_found")
    set_public_tenant_context(session, tenant_id=profile.tenant_id)
    tenant = public_catalog_repository.get_active_tenant(
        session,
        tenant_id=profile.tenant_id,
    )
    if tenant is None:
        raise ApplicationError("STORE_NOT_FOUND", "Store was not found.", kind="not_found")
    return tenant, profile


def public_widget(profile: TenantPublicProfileRow) -> PublicSupportWidgetResponse:
    settings = settings_response(profile)
    return PublicSupportWidgetResponse(
        welcome_message=settings.welcome_message,
        custom_actions=[row for row in settings.custom_actions if row.visible],
    )


def get_public_action_image(
    session: Session,
    *,
    slug: str,
    slot: int,
) -> tuple[bytes, str]:
    tenant, profile = _resolve_public_store(session, slug=slug)
    action = _stored_actions(profile).get(slot, {})
    media_value = str(action.get("image_media_id") or "").strip()
    try:
        media_id = UUID(media_value)
    except (TypeError, ValueError) as exc:
        raise ApplicationError(
            "SUPPORT_IMAGE_NOT_FOUND",
            "悬浮球图片不存在。",
            kind="not_found",
        ) from exc
    media = session.scalar(
        select(MediaObjectRow).where(
            MediaObjectRow.tenant_id == tenant.id,
            MediaObjectRow.id == media_id,
            MediaObjectRow.status == "AVAILABLE",
            MediaObjectRow.scan_status == "CLEAN",
            MediaObjectRow.zone == "APPROVED_MEDIA",
        )
    )
    if media is None:
        raise ApplicationError(
            "SUPPORT_IMAGE_NOT_FOUND",
            "悬浮球图片不存在。",
            kind="not_found",
        )
    try:
        with get_object_storage().materialize(media.object_key) as path:
            return path.read_bytes(), media.detected_media_type or "image/webp"
    except FileNotFoundError as exc:
        raise ApplicationError(
            "SUPPORT_IMAGE_NOT_FOUND",
            "悬浮球图片不存在。",
            kind="not_found",
        ) from exc


def _message_response(row: StorefrontChatMessageRow) -> SupportChatMessageResponse:
    return SupportChatMessageResponse(
        id=row.id,
        sender_type=row.sender_type,
        body=row.body,
        created_at=row.created_at,
    )


def _public_conversation_response(
    session: Session,
    row: StorefrontChatConversationRow,
    *,
    access_token: str | None = None,
) -> PublicChatConversationResponse:
    return PublicChatConversationResponse(
        id=row.id,
        reference_number=row.reference_number,
        status=row.status,
        messages=[
            _message_response(message)
            for message in repository.list_messages(
                session,
                tenant_id=row.tenant_id,
                conversation_id=row.id,
            )
        ],
        access_token=access_token,
    )


def create_public_conversation(
    session: Session,
    *,
    slug: str,
    request: PublicChatConversationCreate,
) -> PublicChatConversationResponse:
    tenant, _ = _resolve_public_store(session, slug=slug)
    now = utcnow()
    token = new_secret()
    conversation_id = uuid4()
    row = StorefrontChatConversationRow(
        id=conversation_id,
        tenant_id=tenant.id,
        reference_number=f"CS-{now:%Y%m%d}-{conversation_id.hex[:8].upper()}",
        visitor_token_hash=hash_secret(token),
        visitor_name=request.visitor_name,
        visitor_email=request.visitor_email,
        locale=request.locale.strip() or "zh-CN",
        status="OPEN",
        last_message_at=now,
        last_visitor_message_at=now,
    )
    message = StorefrontChatMessageRow(
        tenant_id=tenant.id,
        conversation_id=conversation_id,
        sender_type="VISITOR",
        client_message_id=request.client_message_id,
        body=request.message,
    )
    session.add_all([row, message])
    session.commit()
    session.refresh(row)
    return _public_conversation_response(session, row, access_token=token)


def _public_conversation(
    session: Session,
    *,
    slug: str,
    token: str,
) -> StorefrontChatConversationRow:
    tenant, _ = _resolve_public_store(session, slug=slug)
    if not token or len(token) > 500:
        raise ApplicationError(
            "SUPPORT_SESSION_INVALID",
            "客服会话已失效，请重新发起咨询。",
            kind="unauthorized",
        )
    row = repository.get_conversation_by_token_hash(
        session,
        tenant_id=tenant.id,
        token_hash=hash_secret(token),
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_SESSION_INVALID",
            "客服会话已失效，请重新发起咨询。",
            kind="unauthorized",
        )
    return row


def get_public_conversation(
    session: Session,
    *,
    slug: str,
    token: str,
) -> PublicChatConversationResponse:
    row = _public_conversation(session, slug=slug, token=token)
    return _public_conversation_response(session, row)


def send_public_message(
    session: Session,
    *,
    slug: str,
    token: str,
    request: PublicChatMessageWrite,
) -> PublicChatConversationResponse:
    row = _public_conversation(session, slug=slug, token=token)
    if row.status != "OPEN":
        raise ApplicationError(
            "SUPPORT_CONVERSATION_CLOSED",
            "本次会话已经结束，请发起新的咨询。",
            kind="conflict",
        )
    existing = repository.find_client_message(
        session,
        tenant_id=row.tenant_id,
        conversation_id=row.id,
        client_message_id=request.client_message_id,
    )
    if existing is None:
        now = utcnow()
        session.add(
            StorefrontChatMessageRow(
                tenant_id=row.tenant_id,
                conversation_id=row.id,
                sender_type="VISITOR",
                client_message_id=request.client_message_id,
                body=request.message,
            )
        )
        row.last_message_at = now
        row.last_visitor_message_at = now
        session.commit()
        session.refresh(row)
    return _public_conversation_response(session, row)


def _summary(
    row: StorefrontChatConversationRow,
    preview: str,
) -> SupportConversationSummaryResponse:
    return SupportConversationSummaryResponse(
        id=row.id,
        reference_number=row.reference_number,
        visitor_name=row.visitor_name,
        visitor_email=row.visitor_email,
        locale=row.locale,
        status=row.status,
        last_message_preview=preview[:160],
        last_message_at=row.last_message_at,
        unread=repository.has_unread_visitor_message(row),
    )


def list_conversations(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    page: int,
    page_size: int,
    status: str | None,
    query: str,
) -> SupportConversationPageResponse:
    _require(permissions, "support.view")
    rows, total = repository.list_conversations(
        session,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        status=status,
        query=query,
    )
    return SupportConversationPageResponse(
        items=[_summary(row, preview) for row, preview in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


def get_conversation(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    permissions: frozenset[str],
) -> SupportConversationDetailResponse:
    _require(permissions, "support.view")
    row = repository.get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_CONVERSATION_NOT_FOUND",
            "客服会话不存在。",
            kind="not_found",
        )
    row.merchant_last_read_at = utcnow()
    messages = repository.list_messages(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
    )
    preview = messages[-1].body if messages else ""
    session.commit()
    summary = _summary(row, preview)
    return SupportConversationDetailResponse(
        **summary.model_dump(),
        messages=[_message_response(message) for message in messages],
    )


def send_merchant_message(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    permissions: frozenset[str],
    request: SupportMerchantMessageWrite,
) -> SupportConversationDetailResponse:
    _require(permissions, "support.reply")
    row = repository.get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_CONVERSATION_NOT_FOUND",
            "客服会话不存在。",
            kind="not_found",
        )
    if row.status != "OPEN":
        raise ApplicationError(
            "SUPPORT_CONVERSATION_CLOSED",
            "会话已结束，请先重新打开。",
            kind="conflict",
        )
    now = utcnow()
    session.add(
        StorefrontChatMessageRow(
            tenant_id=tenant_id,
            conversation_id=row.id,
            sender_type="MERCHANT",
            sender_user_id=user_id,
            body=request.message,
        )
    )
    row.last_message_at = now
    row.last_merchant_message_at = now
    row.merchant_last_read_at = now
    session.commit()
    return get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
        permissions=frozenset({"support.view"}),
    )


def update_conversation_status(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    permissions: frozenset[str],
    request: SupportConversationStatusUpdate,
) -> SupportConversationDetailResponse:
    _require(permissions, "support.reply")
    row = repository.get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_CONVERSATION_NOT_FOUND",
            "客服会话不存在。",
            kind="not_found",
        )
    row.status = request.status
    session.commit()
    return get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
        permissions=frozenset({"support.view"}),
    )
