from __future__ import annotations

import hashlib
import io
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..ai_data_models import AITaskRow
from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
from ..file_security_models import MediaObjectRow
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import public_catalog_repository
from ..repositories import support_repository as repository
from ..services.auth.tokens import hash_secret, new_secret
from ..services.storefront_analytics import VisitorLocation
from ..services.translation import (
    TranslationProviderError,
    catalog_translation_is_configured,
    configured_catalog_translator,
)
from ..services.translation_memory import translate_values_with_memory
from ..services.translation_configuration import (
    resolved_catalog_translator,
    translation_provider_is_configured,
)
from ..storefront_locales import StorefrontLocale, normalize_storefront_locale
from ..support_models import (
    StorefrontChatConversationRow,
    StorefrontChatMessageRow,
)
from ..support_ai_models import SupportAIEvidenceUseRow, SupportAIRunRow
from ..support_schemas import (
    PublicChatConversationCreate,
    PublicChatConversationResponse,
    PublicChatMessageWrite,
    PublicSupportChatMessageResponse,
    PublicSupportWidgetResponse,
    SupportChatMessageResponse,
    SupportCitationResponse,
    SupportConversationAutomationUpdate,
    SupportConversationDetailResponse,
    SupportConversationPageResponse,
    SupportConversationStatusUpdate,
    SupportConversationSummaryResponse,
    SupportCustomActionResponse,
    SupportHumanRequestResponse,
    SupportHumanRequestSummaryResponse,
    SupportMerchantMessageWrite,
    SupportSettingsResponse,
    SupportSettingsUpdate,
    SupportTranslationPreviewResponse,
    SupportTranslationPreviewWrite,
)


DEFAULT_WELCOME_MESSAGE = "您好，请告诉我们您正在寻找什么商品，我们会尽快回复。"
MAX_ACTION_IMAGE_BYTES = 5 * 1024 * 1024
TRANSLATION_RETRY_DELAY = timedelta(minutes=2)
INLINE_CITATION_PATTERN = re.compile(r"\[(\d{1,2})\]")

HUMAN_REQUEST_CONFIRMATIONS = {
    "zh": "已通知人工客服，请稍候。",
    "en": "A human support agent has been notified. Please wait a moment.",
    "es": "Se ha avisado a un agente de atención al cliente. Espera un momento.",
    "pt": "Um agente de apoio ao cliente foi notificado. Aguarde um momento.",
    "tr": "Bir müşteri temsilcisine bildirim gönderildi. Lütfen biraz bekleyin.",
    "ar": "تم إشعار موظف خدمة العملاء. يرجى الانتظار قليلاً.",
    "ja": "担当者に通知しました。しばらくお待ちください。",
    "ko": "상담원에게 알림을 보냈습니다. 잠시만 기다려 주세요.",
    "fr": "Un conseiller a été prévenu. Merci de patienter un instant.",
    "fa": "به پشتیبان انسانی اطلاع داده شد. لطفاً کمی منتظر بمانید.",
    "de": "Ein Mitarbeiter wurde benachrichtigt. Bitte warten Sie einen Moment.",
    "it": "Un operatore è stato avvisato. Attendi un momento.",
    "ru": "Оператор поддержки уведомлён. Пожалуйста, немного подождите.",
}


def _require(permissions: frozenset[str], permission: str) -> None:
    if permission not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {permission}",
            kind="forbidden",
        )


def _human_assistance_state(row: StorefrontChatConversationRow) -> str:
    if row.human_handoff_offered_at is None:
        return "NONE"
    if row.human_resolved_at is not None:
        return "RESOLVED"
    if row.human_requested_at is not None:
        return "REQUESTED"
    return "OFFERED"


def _resolve_human_assistance(
    row: StorefrontChatConversationRow,
    *,
    resolved_at: datetime,
) -> None:
    if (
        row.human_handoff_offered_at is not None
        and row.human_resolved_at is None
    ):
        row.human_resolved_at = resolved_at


def _human_request_confirmation(language: str) -> str:
    base = language.strip().replace("_", "-").split("-", 1)[0].casefold()
    return HUMAN_REQUEST_CONFIRMATIONS.get(base) or HUMAN_REQUEST_CONFIRMATIONS["en"]


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
        if item.visible and not item.label:
            raise ApplicationError(
                "SUPPORT_ACTION_LABEL_REQUIRED",
                f"请为第 {slot} 个悬浮球填写标题。",
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
    try:
        with tempfile.NamedTemporaryFile(suffix=".webp") as temporary:
            temporary.write(processed)
            temporary.flush()
            get_object_storage().put_file(
                Path(temporary.name),
                object_key=object_key,
                content_type="image/webp",
            )
    except Exception as exc:
        raise ApplicationError(
            "SUPPORT_IMAGE_STORAGE_UNAVAILABLE",
            "图片上传到对象存储失败，请联系平台管理员。",
            kind="unavailable",
        ) from exc
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


def public_widget(
    session: Session,
    profile: TenantPublicProfileRow,
) -> PublicSupportWidgetResponse:
    settings = settings_response(profile)
    from ..services.support_ai_configuration import support_ai_provider_is_configured
    from ..services.support_ai_orchestrator import get_support_ai_settings

    ai_settings = get_support_ai_settings(
        session,
        tenant_id=profile.tenant_id,
        create=False,
    )
    ai_enabled = bool(
        ai_settings is not None
        and ai_settings.enabled
        and support_ai_provider_is_configured(
            session, tenant_id=profile.tenant_id
        )
    )
    return PublicSupportWidgetResponse(
        welcome_message=settings.welcome_message,
        ai_enabled=ai_enabled,
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


def _message_citations(
    session: Session,
    row: StorefrontChatMessageRow,
) -> list[SupportCitationResponse]:
    if row.sender_type != "AI":
        return []
    run = session.scalar(
        select(SupportAIRunRow).where(
            SupportAIRunRow.tenant_id == row.tenant_id,
            SupportAIRunRow.output_message_id == row.id,
            SupportAIRunRow.status == "SUCCEEDED",
        )
    )
    if run is None:
        return []
    cited_numbers = {
        int(value)
        for value in (run.decision_trace or {}).get("inline_citations", [])
        if isinstance(value, int)
        or (isinstance(value, str) and value.isdigit())
    }
    if not cited_numbers:
        # Compatibility for completed runs written before every finalization
        # path persisted inline_citations. Evidence rows remain immutable, so
        # parsing the already-published answer safely restores product cards.
        cited_numbers = {
            int(value) for value in INLINE_CITATION_PATTERN.findall(row.body)
        }
    if not cited_numbers:
        return []
    evidence = session.scalars(
        select(SupportAIEvidenceUseRow)
        .where(
            SupportAIEvidenceUseRow.tenant_id == row.tenant_id,
            SupportAIEvidenceUseRow.run_id == run.id,
            SupportAIEvidenceUseRow.citation_number.in_(cited_numbers),
        )
        .order_by(SupportAIEvidenceUseRow.citation_number)
    ).all()
    return [
        SupportCitationResponse(
            citation_number=item.citation_number,
            source_type=item.source_type,
            source_entity_id=item.source_entity_id,
            source_title=item.source_title,
            source_version=int(item.source_version),
            classification=item.classification,
            locator=item.locator,
            excerpt=item.excerpt,
            score=float(item.score),
        )
        for item in evidence
    ]


def _public_message_response(
    session: Session,
    row: StorefrontChatMessageRow,
) -> PublicSupportChatMessageResponse:
    return PublicSupportChatMessageResponse(
        id=row.id,
        sender_type=row.sender_type,
        body=row.body,
        created_at=row.created_at,
        citations=_message_citations(session, row),
    )


def _message_response(
    session: Session,
    row: StorefrontChatMessageRow,
) -> SupportChatMessageResponse:
    return SupportChatMessageResponse(
        id=row.id,
        sender_type=row.sender_type,
        body=row.body,
        draft_body=row.draft_body,
        translated_body=row.translated_body,
        translation_source_locale=row.translation_source_locale,
        translation_target_locale=row.translation_target_locale,
        translation_status=row.translation_status,
        created_at=row.created_at,
        citations=_message_citations(session, row),
    )


def _ai_processing(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> bool:
    processing, _stage = _ai_processing_state(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    return processing


def _ai_processing_state(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> tuple[bool, str | None]:
    row = session.execute(
        select(SupportAIRunRow.status, AITaskRow.progress)
        .join(
            AITaskRow,
            (AITaskRow.tenant_id == SupportAIRunRow.tenant_id)
            & (AITaskRow.id == SupportAIRunRow.ai_task_id),
        )
        .where(
            SupportAIRunRow.tenant_id == tenant_id,
            SupportAIRunRow.conversation_id == conversation_id,
            SupportAIRunRow.status.in_(["QUEUED", "RUNNING"]),
        )
        .order_by(SupportAIRunRow.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return False, None
    status, progress = row
    if status == "QUEUED" or int(progress or 0) <= 10:
        return True, "USING_TOOLS"
    if int(progress or 0) < 55:
        return True, "RAG_SEARCH"
    return True, "COMPOSING"


def _merchant_reading_locale(
    session: Session,
    *,
    tenant_id: UUID,
) -> StorefrontLocale:
    tenant = session.get(TenantRow, tenant_id)
    if tenant is not None and str(tenant.default_currency).upper() == "USD":
        return "en-US"
    return "zh-CN"


def _visitor_locale(row: StorefrontChatConversationRow) -> StorefrontLocale:
    return normalize_storefront_locale(row.locale) or "zh-CN"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _translate_visitor_messages(
    session: Session,
    *,
    conversation: StorefrontChatConversationRow,
    messages: list[StorefrontChatMessageRow],
    force: bool = False,
) -> None:
    target_locale = _merchant_reading_locale(
        session,
        tenant_id=conversation.tenant_id,
    )
    fallback_source = _visitor_locale(conversation)
    now = utcnow()
    candidates: list[StorefrontChatMessageRow] = []
    changed = False
    provider_configured = translation_provider_is_configured(
        session,
        environment_check=catalog_translation_is_configured,
    )

    for message in messages:
        if message.sender_type != "VISITOR":
            continue
        source_locale = (
            normalize_storefront_locale(message.translation_source_locale)
            or fallback_source
        )
        metadata_changed = (
            message.translation_source_locale != source_locale
            or message.translation_target_locale != target_locale
        )
        if metadata_changed:
            message.translation_source_locale = source_locale
            message.translation_target_locale = target_locale
            message.translated_body = None
            message.translation_status = "PENDING"
            changed = True

        if source_locale == target_locale:
            if (
                message.translation_status != "NOT_REQUIRED"
                or message.translated_body is not None
            ):
                message.translation_status = "NOT_REQUIRED"
                message.translated_body = None
                changed = True
            continue
        if message.translation_status == "READY" and message.translated_body:
            continue
        if (
            not force
            and message.translation_status == "FAILED"
            and now - _as_utc(message.updated_at) < TRANSLATION_RETRY_DELAY
        ):
            continue
        if not provider_configured:
            if message.translation_status != "UNAVAILABLE":
                message.translation_status = "UNAVAILABLE"
                changed = True
            continue
        candidates.append(message)

    if candidates:
        try:
            translator = resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            )
        except TranslationProviderError:
            for message in candidates:
                message.translation_status = "UNAVAILABLE"
                changed = True
        else:
            for message in candidates:
                translations = translate_values_with_memory(
                    tenant_id=conversation.tenant_id,
                    translator=translator,
                    values=[message.body],
                    source_locale="auto",
                    target_locale=target_locale,
                )
                translated = translations.get(message.body, "").strip()
                if translated:
                    message.translated_body = translated
                    message.translation_status = "READY"
                else:
                    message.translated_body = None
                    message.translation_status = "FAILED"
                changed = True
    if changed:
        session.commit()


def _public_conversation_response(
    session: Session,
    row: StorefrontChatConversationRow,
    *,
    access_token: str | None = None,
) -> PublicChatConversationResponse:
    ai_processing, ai_processing_stage = _ai_processing_state(
        session,
        tenant_id=row.tenant_id,
        conversation_id=row.id,
    )
    return PublicChatConversationResponse(
        id=row.id,
        reference_number=row.reference_number,
        status=row.status,
        messages=[
            _public_message_response(session, message)
            for message in repository.list_messages(
                session,
                tenant_id=row.tenant_id,
                conversation_id=row.id,
            )
        ],
        access_token=access_token,
        automation_state=row.automation_state,
        ai_processing=ai_processing,
        ai_processing_stage=ai_processing_stage,
        human_assistance_state=_human_assistance_state(row),
        human_assistance_requested_at=row.human_requested_at,
    )


def create_public_conversation(
    session: Session,
    *,
    slug: str,
    request: PublicChatConversationCreate,
    owner_membership_id: UUID | None = None,
    visitor_ip: str | None = None,
    visitor_location: VisitorLocation | None = None,
) -> PublicChatConversationResponse:
    tenant, _ = _resolve_public_store(session, slug=slug)
    now = utcnow()
    token = new_secret()
    conversation_id = uuid4()
    row = StorefrontChatConversationRow(
        id=conversation_id,
        tenant_id=tenant.id,
        owner_membership_id=owner_membership_id,
        reference_number=f"CS-{now:%Y%m%d}-{conversation_id.hex[:8].upper()}",
        visitor_token_hash=hash_secret(token),
        visitor_name=request.visitor_name,
        visitor_email=request.visitor_email,
        visitor_ip=visitor_ip,
        visitor_country_code=(
            visitor_location.country_code if visitor_location else None
        ),
        visitor_timezone=(
            visitor_location.timezone if visitor_location else None
        ),
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
        translation_source_locale=normalize_storefront_locale(request.locale),
        translation_target_locale=_merchant_reading_locale(
            session,
            tenant_id=tenant.id,
        ),
        translation_status="PENDING",
    )
    session.add_all([row, message])
    session.flush()
    from ..services.support_ai_orchestrator import enqueue_chat_run

    enqueue_chat_run(session, conversation=row, message=message)
    session.commit()
    # Visitor translation is an operator-side concern and must not delay the
    # acknowledgement or scheduling of the AI reply. Merchant reads still resolve
    # pending translations through get_conversation().
    session.refresh(row)
    return _public_conversation_response(session, row, access_token=token)


def _public_conversation(
    session: Session,
    *,
    slug: str,
    token: str,
    owner_membership_id: UUID | None = None,
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
    if row.owner_membership_id != owner_membership_id:
        # Never infer ownership from possession of a public conversation token.
        # Older unowned sessions remain in the merchant inbox; a child account
        # starts a fresh account-owned session instead of being able to claim it.
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
    owner_membership_id: UUID | None = None,
) -> PublicChatConversationResponse:
    row = _public_conversation(
        session,
        slug=slug,
        token=token,
        owner_membership_id=owner_membership_id,
    )
    return _public_conversation_response(session, row)


def latest_public_chat_run(
    session: Session,
    *,
    conversation_id: UUID,
) -> SupportAIRunRow | None:
    """Return the newest chat run for an already authorized public conversation."""

    return session.scalar(
        select(SupportAIRunRow)
        .where(
            SupportAIRunRow.conversation_id == conversation_id,
            SupportAIRunRow.trigger_type == "CHAT",
        )
        .order_by(SupportAIRunRow.created_at.desc())
        .limit(1)
    )


def send_public_message(
    session: Session,
    *,
    slug: str,
    token: str,
    request: PublicChatMessageWrite,
    owner_membership_id: UUID | None = None,
    visitor_ip: str | None = None,
    visitor_location: VisitorLocation | None = None,
) -> PublicChatConversationResponse:
    row = _public_conversation(
        session,
        slug=slug,
        token=token,
        owner_membership_id=owner_membership_id,
    )
    location_changed = False
    if visitor_ip and visitor_location:
        if not row.visitor_ip:
            row.visitor_ip = visitor_ip
            location_changed = True
        if row.visitor_country_code != visitor_location.country_code:
            row.visitor_country_code = visitor_location.country_code
            location_changed = True
        if row.visitor_timezone != visitor_location.timezone:
            row.visitor_timezone = visitor_location.timezone
            location_changed = True
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
        source_locale = request.locale or _visitor_locale(row)
        existing = StorefrontChatMessageRow(
            tenant_id=row.tenant_id,
            conversation_id=row.id,
            sender_type="VISITOR",
            client_message_id=request.client_message_id,
            body=request.message,
            translation_source_locale=source_locale,
            translation_target_locale=_merchant_reading_locale(
                session,
                tenant_id=row.tenant_id,
            ),
            translation_status="PENDING",
        )
        session.add(existing)
        row.last_message_at = now
        row.last_visitor_message_at = now
        row.locale = source_locale
        session.flush()
        from ..services.support_ai_orchestrator import enqueue_chat_run

        enqueue_chat_run(session, conversation=row, message=existing)
        session.commit()
        session.refresh(row)
    elif location_changed:
        # A retried client message is idempotent, but a newly resolved visitor
        # location still needs to be persisted for the operator view.
        session.commit()
        session.refresh(row)
    return _public_conversation_response(session, row)


def request_public_human_assistance(
    session: Session,
    *,
    slug: str,
    token: str,
    owner_membership_id: UUID | None = None,
) -> PublicChatConversationResponse:
    authenticated = _public_conversation(
        session,
        slug=slug,
        token=token,
        owner_membership_id=owner_membership_id,
    )
    row = repository.get_conversation_for_update(
        session,
        tenant_id=authenticated.tenant_id,
        conversation_id=authenticated.id,
    )
    assert row is not None
    if row.status != "OPEN":
        raise ApplicationError(
            "SUPPORT_CONVERSATION_CLOSED",
            "本次会话已经结束，请发起新的咨询。",
            kind="conflict",
        )
    state = _human_assistance_state(row)
    if state == "REQUESTED":
        return _public_conversation_response(session, row)
    if state != "OFFERED" or row.automation_state != "HUMAN_TAKEOVER":
        raise ApplicationError(
            "SUPPORT_HUMAN_ASSISTANCE_NOT_AVAILABLE",
            "当前会话暂未进入人工协助流程。",
            kind="conflict",
        )
    messages = repository.list_messages(
        session,
        tenant_id=row.tenant_id,
        conversation_id=row.id,
    )
    language = next(
        (
            message.translation_source_locale
            for message in reversed(messages)
            if message.sender_type == "SYSTEM"
            and message.translation_source_locale
        ),
        row.locale,
    )
    now = utcnow()
    row.human_requested_at = now
    row.human_resolved_at = None
    row.human_request_reason = "VISITOR_CONFIRMED_AI_HANDOFF"
    row.automation_state = "HUMAN_TAKEOVER"
    row.automation_state_changed_at = now
    row.last_message_at = now
    session.add(
        StorefrontChatMessageRow(
            tenant_id=row.tenant_id,
            conversation_id=row.id,
            sender_type="SYSTEM",
            body=_human_request_confirmation(str(language or row.locale)),
            translation_source_locale=language or row.locale,
            translation_target_locale=language or row.locale,
            translation_status="NOT_REQUIRED",
        )
    )
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
        visitor_country_code=row.visitor_country_code,
        visitor_timezone=row.visitor_timezone,
        locale=row.locale,
        status=row.status,
        last_message_preview=preview[:160],
        last_message_at=row.last_message_at,
        unread=repository.has_unread_visitor_message(row),
        automation_state=row.automation_state,
        ai_processing=False,
        human_assistance_state=_human_assistance_state(row),
        human_assistance_requested_at=row.human_requested_at,
    )


def _operator_owner_membership_id(
    *,
    membership_id: UUID,
    account_scope: str,
) -> UUID | None:
    return membership_id if account_scope == "CUSTOMER_SUBACCOUNT" else None


def _require_operator_conversation(
    row: StorefrontChatConversationRow | None,
    *,
    membership_id: UUID,
    account_scope: str,
) -> StorefrontChatConversationRow:
    expected_owner = _operator_owner_membership_id(
        membership_id=membership_id,
        account_scope=account_scope,
    )
    if row is None or row.owner_membership_id != expected_owner:
        # Deliberately return not-found for another account's conversation so
        # callers cannot use ids to discover sibling or parent conversations.
        raise ApplicationError(
            "SUPPORT_CONVERSATION_NOT_FOUND",
            "客服会话不存在。",
            kind="not_found",
        )
    return row


def list_human_requests(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    membership_id: UUID,
    account_scope: str,
    limit: int,
) -> SupportHumanRequestSummaryResponse:
    _require(permissions, "support.view")
    rows, total = repository.list_pending_human_requests(
        session,
        tenant_id=tenant_id,
        limit=limit,
        owner_membership_id=_operator_owner_membership_id(
            membership_id=membership_id,
            account_scope=account_scope,
        ),
    )
    return SupportHumanRequestSummaryResponse(
        pending_count=total,
        items=[
            SupportHumanRequestResponse(
                conversation_id=row.id,
                reference_number=row.reference_number,
                visitor_name=row.visitor_name,
                visitor_email=row.visitor_email,
                locale=row.locale,
                message_preview=preview[:240],
                requested_at=row.human_requested_at,
            )
            for row, preview in rows
            if row.human_requested_at is not None
        ],
    )


def list_conversations(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    membership_id: UUID,
    account_scope: str,
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
        preview_locale=_merchant_reading_locale(session, tenant_id=tenant_id),
        owner_membership_id=_operator_owner_membership_id(
            membership_id=membership_id,
            account_scope=account_scope,
        ),
    )
    return SupportConversationPageResponse(
        items=[
            _summary(row, preview).model_copy(
                update={
                    "ai_processing": _ai_processing(
                        session,
                        tenant_id=tenant_id,
                        conversation_id=row.id,
                    )
                }
            )
            for row, preview in rows
        ],
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
    membership_id: UUID,
    account_scope: str,
) -> SupportConversationDetailResponse:
    _require(permissions, "support.view")
    row = repository.get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    row = _require_operator_conversation(
        row,
        membership_id=membership_id,
        account_scope=account_scope,
    )
    row.merchant_last_read_at = utcnow()
    messages = repository.list_messages(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
    )
    _translate_visitor_messages(
        session,
        conversation=row,
        messages=messages,
    )
    last_message = messages[-1] if messages else None
    preview = (
        last_message.translated_body
        if last_message is not None
        and last_message.translation_status == "READY"
        and last_message.translation_target_locale
        == _merchant_reading_locale(session, tenant_id=tenant_id)
        and last_message.translated_body
        else last_message.body if last_message is not None else ""
    )
    session.commit()
    summary = _summary(row, preview).model_copy(
        update={
            "ai_processing": _ai_processing(
                session,
                tenant_id=tenant_id,
                conversation_id=row.id,
            )
        }
    )
    return SupportConversationDetailResponse(
        **summary.model_dump(),
        messages=[_message_response(session, message) for message in messages],
    )


def send_merchant_message(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    account_scope: str,
    conversation_id: UUID,
    permissions: frozenset[str],
    request: SupportMerchantMessageWrite,
) -> SupportConversationDetailResponse:
    _require(permissions, "support.reply")
    row = repository.get_conversation_for_update(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    row = _require_operator_conversation(
        row,
        membership_id=membership_id,
        account_scope=account_scope,
    )
    if row.status != "OPEN":
        raise ApplicationError(
            "SUPPORT_CONVERSATION_CLOSED",
            "会话已结束，请先重新打开。",
            kind="conflict",
        )
    now = utcnow()
    row.automation_state = "HUMAN_TAKEOVER"
    row.automation_state_changed_at = now
    _resolve_human_assistance(row, resolved_at=now)
    from ..services.support_ai_orchestrator import cancel_queued_runs_for_conversation

    cancel_queued_runs_for_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
        reason="MERCHANT_REPLIED",
    )
    source_locale = _merchant_reading_locale(session, tenant_id=tenant_id)
    target_locale = source_locale
    translation_status = "NOT_REQUIRED"
    if request.draft_message is not None:
        if request.source_locale != source_locale:
            raise ApplicationError(
                "SUPPORT_TRANSLATION_SOURCE_MISMATCH",
                "回复原文语言与当前内外贸版本不一致，请重新翻译。",
                kind="conflict",
            )
        target_locale = request.target_locale or _visitor_locale(row)
        translation_status = "READY"
    session.add(
        StorefrontChatMessageRow(
            tenant_id=tenant_id,
            conversation_id=row.id,
            sender_type="MERCHANT",
            sender_user_id=user_id,
            body=request.message,
            draft_body=request.draft_message,
            translation_source_locale=source_locale,
            translation_target_locale=target_locale,
            translation_status=translation_status,
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
        membership_id=membership_id,
        account_scope=account_scope,
    )


def preview_merchant_message_translation(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    permissions: frozenset[str],
    membership_id: UUID,
    account_scope: str,
    request: SupportTranslationPreviewWrite,
) -> SupportTranslationPreviewResponse:
    _require(permissions, "support.reply")
    row = repository.get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    row = _require_operator_conversation(
        row,
        membership_id=membership_id,
        account_scope=account_scope,
    )
    if row.status != "OPEN":
        raise ApplicationError(
            "SUPPORT_CONVERSATION_CLOSED",
            "会话已结束，请先重新打开。",
            kind="conflict",
        )
    source_locale = _merchant_reading_locale(session, tenant_id=tenant_id)
    target_locale = request.target_locale
    if source_locale == target_locale:
        translated = request.message
    else:
        if not translation_provider_is_configured(
            session,
            environment_check=catalog_translation_is_configured,
        ):
            raise ApplicationError(
                "SUPPORT_TRANSLATION_UNAVAILABLE",
                "翻译服务尚未配置，请联系平台管理员。",
                kind="unavailable",
            )
        try:
            translator = resolved_catalog_translator(
                session,
                environment_factory=configured_catalog_translator,
            )
        except TranslationProviderError as exc:
            raise ApplicationError(
                "SUPPORT_TRANSLATION_UNAVAILABLE",
                "翻译服务暂不可用，请稍后重试。",
                kind="unavailable",
            ) from exc
        translations = translate_values_with_memory(
            tenant_id=tenant_id,
            translator=translator,
            values=[request.message],
            source_locale=source_locale,
            target_locale=target_locale,
        )
        translated = translations.get(request.message, "").strip()
        if not translated:
            raise ApplicationError(
                "SUPPORT_TRANSLATION_FAILED",
                "这条回复暂时无法翻译，请稍后重试或直接编辑后发送。",
                kind="unavailable",
            )
    return SupportTranslationPreviewResponse(
        source_locale=source_locale,
        target_locale=target_locale,
        original_message=request.message,
        translated_message=translated,
    )


def update_conversation_status(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    permissions: frozenset[str],
    membership_id: UUID,
    account_scope: str,
    request: SupportConversationStatusUpdate,
) -> SupportConversationDetailResponse:
    _require(permissions, "support.reply")
    row = repository.get_conversation_for_update(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    row = _require_operator_conversation(
        row,
        membership_id=membership_id,
        account_scope=account_scope,
    )
    row.status = request.status
    if request.status == "CLOSED":
        _resolve_human_assistance(row, resolved_at=utcnow())
    session.commit()
    return get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
        permissions=frozenset({"support.view"}),
        membership_id=membership_id,
        account_scope=account_scope,
    )


def update_conversation_automation(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    permissions: frozenset[str],
    is_platform_admin: bool,
    membership_id: UUID,
    account_scope: str,
    request: SupportConversationAutomationUpdate,
) -> SupportConversationDetailResponse:
    if request.automation_state == "HUMAN_TAKEOVER":
        _require(permissions, "support.reply")
        raise ApplicationError(
            "SUPPORT_TAKEOVER_REQUIRES_REPLY_OR_AI_HANDOFF",
            "人工接管只能在客服实际发送回复，或 AI 明确转交人工时发生。",
            kind="conflict",
        )
    if not is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "只有平台管理员可以恢复 AI 接待。",
            kind="forbidden",
        )
    row = repository.get_conversation_for_update(
        session,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    row = _require_operator_conversation(
        row,
        membership_id=membership_id,
        account_scope=account_scope,
    )
    if row.automation_state != "AI_ACTIVE":
        row.automation_state = "AI_ACTIVE"
        now = utcnow()
        row.automation_state_changed_at = now
        _resolve_human_assistance(row, resolved_at=now)
    session.commit()
    return get_conversation(
        session,
        tenant_id=tenant_id,
        conversation_id=row.id,
        permissions=frozenset({"support.view"}),
        membership_id=membership_id,
        account_scope=account_scope,
    )
