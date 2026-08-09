from __future__ import annotations

import hashlib
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters.file_scanner import get_file_scanner
from ..adapters.object_storage import get_object_storage
from ..domain.errors import ApplicationError
from ..database import set_request_context
from ..file_security_models import MediaObjectRow
from ..identity_models import TenantRow
from ..knowledge_embedding_models import KnowledgeDocumentRow
from ..model_mixins import utcnow
from ..services.auth.dependencies import RequestContext
from ..services.chat_generation import ChatGenerationError
from ..services.support_ai_configuration import (
    copy_support_ai_provider_profile,
    get_managed_support_ai_provider,
    list_managed_support_ai_providers,
    save_managed_support_ai_provider,
    save_support_ai_provider_profile,
    support_ai_provider_is_configured,
    support_ai_provider_snapshot,
)
from ..services.support_ai_orchestrator import (
    create_test_run,
    get_support_ai_settings,
    process_support_ai_run,
)
from ..support_ai_models import (
    SupportAIEvidenceUseRow,
    SupportAIIngestionJobRow,
    SupportAIKnowledgeSourceRow,
    SupportAIProviderSettingsRow,
    SupportAIRunRow,
    SupportAISettingsRow,
)
from ..support_ai_schemas import (
    SupportAIEvidenceResponse,
    SupportAIIngestionJobResponse,
    SupportAIKnowledgeSourceResponse,
    SupportAIKnowledgeSourceUpdate,
    SupportAIKnowledgeUploadResponse,
    SupportAIProviderProfileCopy,
    SupportAIProviderProfileWrite,
    SupportAIProviderSettingsResponse,
    SupportAIProviderSettingsUpdate,
    SupportAIRunPageResponse,
    SupportAIRunResponse,
    SupportAISettingsResponse,
    SupportAISettingsUpdate,
    SupportAIStoreConfigurationCopy,
    SupportAIStoreConfigurationResponse,
    SupportAIStoreProviderBindingUpdate,
    SupportAIStoreProviderBulkBinding,
    SupportAITestRunRequest,
)


MAX_KNOWLEDGE_FILE_BYTES = 25 * 1024 * 1024
SUPPORTED_KNOWLEDGE_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _require(permissions: frozenset[str], permission: str) -> None:
    if permission not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {permission}",
            kind="forbidden",
        )


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def _provider_response(
    session: Session,
    *,
    profile_id: str | None = None,
) -> SupportAIProviderSettingsResponse:
    return SupportAIProviderSettingsResponse(
        **asdict(support_ai_provider_snapshot(session, profile_id=profile_id))
    )


def get_provider_settings(
    session: Session,
    *,
    context: RequestContext,
) -> SupportAIProviderSettingsResponse:
    _require_platform_admin(context)
    try:
        return _provider_response(session)
    except (ChatGenerationError, ValueError) as exc:
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_CONFIGURATION_INVALID",
            str(exc),
        ) from exc


def update_provider_settings(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAIProviderSettingsUpdate,
) -> SupportAIProviderSettingsResponse:
    _require_platform_admin(context)
    try:
        save_managed_support_ai_provider(
            session,
            configuration_name=request.configuration_name,
            display_model_name=request.display_model_name,
            enabled=request.enabled,
            base_url=request.base_url,
            model_name=request.model_name,
            timeout_seconds=request.timeout_seconds,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            api_key=(
                request.api_key.get_secret_value()
                if request.api_key is not None
                else None
            ),
            updated_by_user_id=context.user_id,
        )
        session.commit()
        return _provider_response(session)
    except (ChatGenerationError, ValueError) as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_CONFIGURATION_INVALID",
            str(exc),
        ) from exc


def list_provider_profiles(
    session: Session,
    *,
    context: RequestContext,
) -> list[SupportAIProviderSettingsResponse]:
    _require_platform_admin(context)
    return [
        _provider_response(session, profile_id=row.id)
        for row in list_managed_support_ai_providers(session)
    ]


def _profile_name_available(
    session: Session,
    *,
    configuration_name: str,
    excluding_id: str | None = None,
) -> bool:
    predicate = func.lower(SupportAIProviderSettingsRow.configuration_name) == (
        configuration_name.strip().casefold()
    )
    if excluding_id is not None:
        predicate = predicate & (SupportAIProviderSettingsRow.id != excluding_id)
    return session.scalar(
        select(SupportAIProviderSettingsRow.id).where(
            predicate,
            SupportAIProviderSettingsRow.deleted_at.is_(None),
        )
    ) is None


def _save_profile(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAIProviderProfileWrite,
    profile_id: str | None,
) -> SupportAIProviderSettingsResponse:
    _require_platform_admin(context)
    if profile_id is not None and get_managed_support_ai_provider(
        session, profile_id
    ) is None:
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_PROFILE_NOT_FOUND",
            "大模型 API 配置不存在。",
            kind="not_found",
        )
    if not _profile_name_available(
        session,
        configuration_name=request.configuration_name,
        excluding_id=profile_id,
    ):
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_PROFILE_NAME_CONFLICT",
            "API 配置名称已存在。",
            kind="conflict",
        )
    try:
        row = save_support_ai_provider_profile(
            session,
            profile_id=profile_id,
            configuration_name=request.configuration_name,
            display_model_name=request.display_model_name,
            enabled=request.enabled,
            base_url=request.base_url,
            model_name=request.model_name,
            timeout_seconds=request.timeout_seconds,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            api_key=(
                request.api_key.get_secret_value()
                if request.api_key is not None
                else None
            ),
            updated_by_user_id=context.user_id,
        )
        session.commit()
        return _provider_response(session, profile_id=row.id)
    except (ChatGenerationError, IntegrityError, ValueError) as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_CONFIGURATION_INVALID",
            str(exc),
        ) from exc


def create_provider_profile(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAIProviderProfileWrite,
) -> SupportAIProviderSettingsResponse:
    return _save_profile(
        session,
        context=context,
        request=request,
        profile_id=None,
    )


def update_provider_profile(
    session: Session,
    *,
    context: RequestContext,
    profile_id: str,
    request: SupportAIProviderProfileWrite,
) -> SupportAIProviderSettingsResponse:
    return _save_profile(
        session,
        context=context,
        request=request,
        profile_id=profile_id,
    )


def copy_provider_profile(
    session: Session,
    *,
    context: RequestContext,
    profile_id: str,
    request: SupportAIProviderProfileCopy,
) -> SupportAIProviderSettingsResponse:
    _require_platform_admin(context)
    source = get_managed_support_ai_provider(session, profile_id)
    if source is None:
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_PROFILE_NOT_FOUND",
            "大模型 API 配置不存在。",
            kind="not_found",
        )
    if not _profile_name_available(
        session, configuration_name=request.configuration_name
    ):
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_PROFILE_NAME_CONFLICT",
            "API 配置名称已存在。",
            kind="conflict",
        )
    try:
        row = copy_support_ai_provider_profile(
            session,
            source=source,
            configuration_name=request.configuration_name,
            updated_by_user_id=context.user_id,
        )
        session.commit()
        return _provider_response(session, profile_id=row.id)
    except (ChatGenerationError, IntegrityError, ValueError) as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_CONFIGURATION_INVALID",
            str(exc),
        ) from exc


@contextmanager
def _tenant_scope(
    session: Session,
    *,
    context: RequestContext,
    tenant: TenantRow,
) -> Iterator[None]:
    set_request_context(
        session,
        organization_id=tenant.organization_id,
        tenant_id=tenant.id,
        user_id=context.user_id,
    )
    try:
        yield
    finally:
        set_request_context(
            session,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )


def _platform_tenant(session: Session, *, tenant_id: UUID) -> TenantRow:
    row = session.scalar(
        select(TenantRow).where(
            TenantRow.id == tenant_id,
            TenantRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND", "店铺不存在。", kind="not_found"
        )
    return row


def _store_configuration_response(
    session: Session,
    *,
    tenant: TenantRow,
) -> SupportAIStoreConfigurationResponse:
    row = get_support_ai_settings(session, tenant_id=tenant.id, create=False)
    snapshot = support_ai_provider_snapshot(session, tenant_id=tenant.id)
    return SupportAIStoreConfigurationResponse(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        organization_id=tenant.organization_id,
        enabled=bool(row.enabled) if row is not None else False,
        provider_profile_id=row.provider_setting_id if row is not None else None,
        model_display_name=snapshot.display_model_name,
        updated_at=row.updated_at if row is not None else None,
    )


def list_store_configurations(
    session: Session,
    *,
    context: RequestContext,
) -> list[SupportAIStoreConfigurationResponse]:
    _require_platform_admin(context)
    tenants = session.scalars(
        select(TenantRow)
        .where(TenantRow.deleted_at.is_(None), TenantRow.status != "archived")
        .order_by(TenantRow.name, TenantRow.id)
    ).all()
    result: list[SupportAIStoreConfigurationResponse] = []
    for tenant in tenants:
        with _tenant_scope(session, context=context, tenant=tenant):
            result.append(_store_configuration_response(session, tenant=tenant))
    return result


def _validate_profile_binding(
    session: Session,
    *,
    profile_id: str | None,
) -> None:
    if profile_id is not None and get_managed_support_ai_provider(
        session, profile_id
    ) is None:
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_PROFILE_NOT_FOUND",
            "大模型 API 配置不存在。",
            kind="not_found",
        )


def bind_store_provider(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    request: SupportAIStoreProviderBindingUpdate,
) -> SupportAIStoreConfigurationResponse:
    _require_platform_admin(context)
    _validate_profile_binding(session, profile_id=request.provider_profile_id)
    tenant = _platform_tenant(session, tenant_id=tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        row = get_support_ai_settings(session, tenant_id=tenant.id, create=True)
        assert row is not None
        row.provider_setting_id = request.provider_profile_id
        row.updated_by_user_id = context.user_id
        row.updated_at = utcnow()
        session.flush()
        response = _store_configuration_response(session, tenant=tenant)
    session.commit()
    return response


def bulk_bind_store_provider(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAIStoreProviderBulkBinding,
) -> list[SupportAIStoreConfigurationResponse]:
    _require_platform_admin(context)
    _validate_profile_binding(session, profile_id=request.provider_profile_id)
    tenants = [
        _platform_tenant(session, tenant_id=tenant_id)
        for tenant_id in dict.fromkeys(request.tenant_ids)
    ]
    responses: list[SupportAIStoreConfigurationResponse] = []
    for tenant in tenants:
        with _tenant_scope(session, context=context, tenant=tenant):
            row = get_support_ai_settings(session, tenant_id=tenant.id, create=True)
            assert row is not None
            row.provider_setting_id = request.provider_profile_id
            row.updated_by_user_id = context.user_id
            row.updated_at = utcnow()
            session.flush()
            responses.append(_store_configuration_response(session, tenant=tenant))
    session.commit()
    return responses


def copy_store_configuration(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAIStoreConfigurationCopy,
) -> list[SupportAIStoreConfigurationResponse]:
    _require_platform_admin(context)
    if not request.copy_model_binding and not request.copy_policy and not request.copy_enabled_state:
        raise ApplicationError(
            "SUPPORT_AI_COPY_SCOPE_REQUIRED",
            "请选择至少一项需要复制的配置。",
        )
    if request.source_tenant_id in request.target_tenant_ids:
        raise ApplicationError(
            "SUPPORT_AI_COPY_TARGET_INVALID",
            "源店铺不能同时作为目标店铺。",
        )
    source_tenant = _platform_tenant(
        session, tenant_id=request.source_tenant_id
    )
    with _tenant_scope(session, context=context, tenant=source_tenant):
        source = get_support_ai_settings(
            session, tenant_id=source_tenant.id, create=True
        )
        assert source is not None
        copied_values = {
            "enabled": source.enabled,
            "provider_setting_id": source.provider_setting_id,
            "sku_knowledge_enabled": source.sku_knowledge_enabled,
            "file_knowledge_enabled": source.file_knowledge_enabled,
            "multilingual_enabled": source.multilingual_enabled,
            "min_retrieval_score": source.min_retrieval_score,
            "min_answer_confidence": source.min_answer_confidence,
            "max_sources": source.max_sources,
            "daily_auto_reply_limit": source.daily_auto_reply_limit,
            "system_prompt": source.system_prompt,
            "handoff_messages": dict(source.handoff_messages or {}),
        }
        session.flush()
    targets = [
        _platform_tenant(session, tenant_id=tenant_id)
        for tenant_id in request.target_tenant_ids
    ]
    responses: list[SupportAIStoreConfigurationResponse] = []
    for tenant in targets:
        with _tenant_scope(session, context=context, tenant=tenant):
            target = get_support_ai_settings(session, tenant_id=tenant.id, create=True)
            assert target is not None
            if request.copy_model_binding:
                target.provider_setting_id = copied_values["provider_setting_id"]
            if request.copy_policy:
                for field in (
                    "sku_knowledge_enabled",
                    "file_knowledge_enabled",
                    "multilingual_enabled",
                    "min_retrieval_score",
                    "min_answer_confidence",
                    "max_sources",
                    "daily_auto_reply_limit",
                    "system_prompt",
                    "handoff_messages",
                ):
                    setattr(target, field, copied_values[field])
                target.prompt_version += 1
            if request.copy_enabled_state:
                target.enabled = bool(copied_values["enabled"])
            target.updated_by_user_id = context.user_id
            target.updated_at = utcnow()
            session.flush()
            responses.append(_store_configuration_response(session, tenant=tenant))
    session.commit()
    return responses


def _settings_response(
    session: Session,
    *,
    tenant_id: UUID,
) -> SupportAISettingsResponse:
    row = get_support_ai_settings(session, tenant_id=tenant_id, create=True)
    assert row is not None
    approved_files = int(
        session.scalar(
            select(func.count(SupportAIKnowledgeSourceRow.id)).where(
                SupportAIKnowledgeSourceRow.tenant_id == tenant_id,
                SupportAIKnowledgeSourceRow.status == "APPROVED",
            )
        )
        or 0
    )
    indexed_products = int(
        session.scalar(
            select(func.count(func.distinct(KnowledgeDocumentRow.source_entity_id))).where(
                KnowledgeDocumentRow.tenant_id == tenant_id,
                KnowledgeDocumentRow.source_entity_type == "PRODUCT",
                KnowledgeDocumentRow.status == "ACTIVE",
                KnowledgeDocumentRow.field_policy_version >= 3,
            )
        )
        or 0
    )
    return SupportAISettingsResponse(
        enabled=row.enabled,
        sku_knowledge_enabled=row.sku_knowledge_enabled,
        file_knowledge_enabled=row.file_knowledge_enabled,
        multilingual_enabled=row.multilingual_enabled,
        min_retrieval_score=float(row.min_retrieval_score),
        min_answer_confidence=float(row.min_answer_confidence),
        max_sources=row.max_sources,
        daily_auto_reply_limit=row.daily_auto_reply_limit,
        system_prompt=row.system_prompt,
        handoff_messages={
            str(key): str(value) for key, value in (row.handoff_messages or {}).items()
        },
        prompt_version=row.prompt_version,
        model_display_name=support_ai_provider_snapshot(
            session, tenant_id=tenant_id
        ).display_model_name,
        approved_file_sources=approved_files,
        indexed_sku_products=indexed_products,
        updated_at=row.updated_at,
    )


def get_settings(
    session: Session,
    *,
    context: RequestContext,
) -> SupportAISettingsResponse:
    if not (
        "support.ai.manage" in context.permissions
        or "support.ai.inspect" in context.permissions
    ):
        _require(context.permissions, "support.ai.manage")
    response = _settings_response(session, tenant_id=context.tenant_id)
    session.commit()
    return response


def update_settings(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAISettingsUpdate,
) -> SupportAISettingsResponse:
    _require(context.permissions, "support.ai.manage")
    if request.enabled and not support_ai_provider_is_configured(
        session, tenant_id=context.tenant_id
    ):
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_REQUIRED",
            "当前店铺的智能客服模型暂不可用，请联系平台服务人员。",
            kind="conflict",
        )
    row = get_support_ai_settings(session, tenant_id=context.tenant_id, create=True)
    assert row is not None
    row.enabled = request.enabled
    row.sku_knowledge_enabled = request.sku_knowledge_enabled
    row.file_knowledge_enabled = request.file_knowledge_enabled
    row.multilingual_enabled = request.multilingual_enabled
    row.min_retrieval_score = request.min_retrieval_score
    row.min_answer_confidence = request.min_answer_confidence
    row.max_sources = request.max_sources
    row.daily_auto_reply_limit = request.daily_auto_reply_limit
    row.system_prompt = request.system_prompt
    row.handoff_messages = request.handoff_messages
    row.prompt_version += 1
    row.updated_by_user_id = context.user_id
    row.updated_at = utcnow()
    session.commit()
    return _settings_response(session, tenant_id=context.tenant_id)


def _source_response(row: SupportAIKnowledgeSourceRow) -> SupportAIKnowledgeSourceResponse:
    return SupportAIKnowledgeSourceResponse(
        id=row.id,
        title=row.title,
        description=row.description,
        source_type="FILE",
        classification=row.classification,
        language=row.language,
        status=row.status,
        original_filename=row.original_filename,
        content_type=row.content_type,
        sha256=row.sha256,
        byte_size=row.byte_size,
        chunk_count=row.chunk_count,
        version=int(row.version),
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        approved_at=row.approved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _job_response(row: SupportAIIngestionJobRow) -> SupportAIIngestionJobResponse:
    return SupportAIIngestionJobResponse(
        id=row.id,
        source_id=row.source_id,
        status=row.status,
        progress=row.progress,
        parser_identifier=row.parser_identifier,
        parser_version=row.parser_version,
        chunks_written=row.chunks_written,
        error_code=row.error_code,
        error_message=row.error_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def list_knowledge_sources(
    session: Session,
    *,
    context: RequestContext,
) -> list[SupportAIKnowledgeSourceResponse]:
    if not (
        "knowledge.manage" in context.permissions
        or "support.ai.inspect" in context.permissions
    ):
        _require(context.permissions, "knowledge.manage")
    rows = session.scalars(
        select(SupportAIKnowledgeSourceRow)
        .where(SupportAIKnowledgeSourceRow.tenant_id == context.tenant_id)
        .order_by(SupportAIKnowledgeSourceRow.created_at.desc())
    ).all()
    return [_source_response(row) for row in rows]


def _knowledge_source(
    session: Session,
    *,
    tenant_id: UUID,
    source_id: UUID,
) -> SupportAIKnowledgeSourceRow:
    row = session.scalar(
        select(SupportAIKnowledgeSourceRow).where(
            SupportAIKnowledgeSourceRow.tenant_id == tenant_id,
            SupportAIKnowledgeSourceRow.id == source_id,
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_SOURCE_NOT_FOUND",
            "知识文件不存在。",
            kind="not_found",
        )
    return row


def upload_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    title: str,
    description: str | None,
    classification: str,
    language: str,
    filename: str | None,
    declared_content_type: str | None,
    content: bytes,
) -> SupportAIKnowledgeUploadResponse:
    _require(context.permissions, "knowledge.manage")
    original_filename = Path(filename or "knowledge-file").name[:500]
    suffix = Path(original_filename).suffix.casefold()
    if suffix not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TYPE_UNSUPPORTED",
            "仅支持 PDF、DOCX、TXT 和 Markdown 文件。",
        )
    if not content:
        raise ApplicationError("SUPPORT_AI_KNOWLEDGE_EMPTY", "请选择知识文件。")
    if len(content) > MAX_KNOWLEDGE_FILE_BYTES:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TOO_LARGE",
            "单个知识文件不能超过 25 MB。",
            kind="too_large",
        )
    if classification not in {"PUBLIC", "CUSTOMER_APPROVED"}:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_CLASSIFICATION_INVALID",
            "知识文件分类无效。",
        )
    source_id = uuid4()
    media_id = uuid4()
    job_id = uuid4()
    resolved_title = title.strip() or Path(original_filename).stem
    if not resolved_title:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TITLE_REQUIRED", "请填写知识文件标题。"
        )
    sha256 = hashlib.sha256(content).hexdigest()
    object_key = f"tenants/{context.tenant_id}/documents/support-ai/{source_id}{suffix}"
    storage = get_object_storage()
    with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
        temporary.write(content)
        temporary.flush()
        path = Path(temporary.name)
        try:
            scan = get_file_scanner().scan(path)
        except Exception as exc:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_SCAN_UNAVAILABLE",
                "文件安全扫描暂不可用，请稍后重试。",
                kind="unavailable",
            ) from exc
        if not scan.clean:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_REJECTED",
                "文件未通过安全扫描，已拒绝上传。",
            )
        try:
            storage.put_file(
                path,
                object_key=object_key,
                content_type=declared_content_type or CONTENT_TYPES[suffix],
            )
        except Exception as exc:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_STORAGE_UNAVAILABLE",
                "知识文件上传到对象存储失败，请检查 Cloudflare R2 配置。",
                kind="unavailable",
            ) from exc
    now = utcnow()
    media = MediaObjectRow(
        id=media_id,
        tenant_id=context.tenant_id,
        object_key=object_key,
        zone="DOCUMENT",
        original_filename=original_filename,
        sha256=sha256,
        byte_size=len(content),
        declared_media_type=declared_content_type,
        detected_media_type=CONTENT_TYPES[suffix],
        status="AVAILABLE",
        scan_status="CLEAN",
        scan_engine=scan.engine,
        scan_result={"detail_code": scan.detail_code},
        scan_at=now,
        retention_class="SOURCE_DEFAULT",
        created_by_user_id=context.user_id,
    )
    source = SupportAIKnowledgeSourceRow(
        id=source_id,
        tenant_id=context.tenant_id,
        source_type="FILE",
        title=resolved_title[:300],
        description=(description or "").strip()[:4000] or None,
        classification=classification,
        language=(language or "und").strip()[:35] or "und",
        status="PROCESSING",
        media_object_id=media_id,
        original_filename=original_filename,
        content_type=CONTENT_TYPES[suffix],
        sha256=sha256,
        byte_size=len(content),
        chunk_count=0,
        version=1,
        created_by_user_id=context.user_id,
    )
    job = SupportAIIngestionJobRow(
        id=job_id,
        tenant_id=context.tenant_id,
        source_id=source_id,
        status="QUEUED",
        progress=0,
        requested_by_user_id=context.user_id,
    )
    try:
        # These rows are connected through tenant-scoped composite foreign keys.
        # Flush each parent explicitly so SQLite and PostgreSQL observe the same
        # insertion order even though the ORM models intentionally have no
        # relationship properties.
        session.add(media)
        session.flush()
        session.add(source)
        session.flush()
        session.add(job)
        session.commit()
    except Exception:
        session.rollback()
        try:
            storage.delete(object_key)
        except Exception:
            pass
        raise
    session.refresh(source)
    session.refresh(job)
    return SupportAIKnowledgeUploadResponse(
        source=_source_response(source),
        job=_job_response(job),
    )


def update_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    source_id: UUID,
    request: SupportAIKnowledgeSourceUpdate,
) -> SupportAIKnowledgeSourceResponse:
    _require(context.permissions, "knowledge.manage")
    row = _knowledge_source(
        session, tenant_id=context.tenant_id, source_id=source_id
    )
    if row.status == "PROCESSING":
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_BUSY",
            "知识文件正在处理，请稍后再修改。",
            kind="conflict",
        )
    classification_changed = row.classification != request.classification
    row.title = request.title
    row.description = request.description
    row.classification = request.classification
    row.language = request.language
    if classification_changed and row.status == "APPROVED":
        row.status = "READY"
        row.approved_at = None
        row.approved_by_user_id = None
    row.version += 1
    session.commit()
    return _source_response(row)


def approve_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    source_id: UUID,
) -> SupportAIKnowledgeSourceResponse:
    _require(context.permissions, "knowledge.approve")
    row = _knowledge_source(
        session, tenant_id=context.tenant_id, source_id=source_id
    )
    if row.status not in {"READY", "APPROVED"} or row.chunk_count <= 0:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_NOT_READY",
            "知识文件尚未完成解析和向量化，暂时不能批准。",
            kind="conflict",
        )
    row.status = "APPROVED"
    row.approved_at = utcnow()
    row.approved_by_user_id = context.user_id
    session.commit()
    return _source_response(row)


def revoke_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    source_id: UUID,
) -> SupportAIKnowledgeSourceResponse:
    _require(context.permissions, "knowledge.manage")
    row = _knowledge_source(
        session, tenant_id=context.tenant_id, source_id=source_id
    )
    row.status = "REVOKED"
    row.approved_at = None
    row.approved_by_user_id = None
    row.version += 1
    session.commit()
    return _source_response(row)


def reindex_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    source_id: UUID,
) -> SupportAIIngestionJobResponse:
    _require(context.permissions, "knowledge.manage")
    row = _knowledge_source(
        session, tenant_id=context.tenant_id, source_id=source_id
    )
    active_job = session.scalar(
        select(SupportAIIngestionJobRow).where(
            SupportAIIngestionJobRow.tenant_id == context.tenant_id,
            SupportAIIngestionJobRow.source_id == source_id,
            SupportAIIngestionJobRow.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active_job is not None:
        return _job_response(active_job)
    job = SupportAIIngestionJobRow(
        id=uuid4(),
        tenant_id=context.tenant_id,
        source_id=row.id,
        status="QUEUED",
        progress=0,
        requested_by_user_id=context.user_id,
    )
    # An approved source keeps serving its last committed chunks while a new
    # version is built.  The ingestion job carries the processing state; only
    # sources without an approved version leave the customer-visible set.
    if row.status != "APPROVED":
        row.status = "PROCESSING"
    row.failure_code = None
    row.failure_message = None
    session.add(job)
    session.commit()
    return _job_response(job)


def get_ingestion_job(
    session: Session,
    *,
    context: RequestContext,
    job_id: UUID,
) -> SupportAIIngestionJobResponse:
    if not (
        "knowledge.manage" in context.permissions
        or "support.ai.inspect" in context.permissions
    ):
        _require(context.permissions, "knowledge.manage")
    row = session.scalar(
        select(SupportAIIngestionJobRow).where(
            SupportAIIngestionJobRow.tenant_id == context.tenant_id,
            SupportAIIngestionJobRow.id == job_id,
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_INGESTION_JOB_NOT_FOUND",
            "知识处理任务不存在。",
            kind="not_found",
        )
    return _job_response(row)


def _evidence_response(row: SupportAIEvidenceUseRow) -> SupportAIEvidenceResponse:
    return SupportAIEvidenceResponse(
        citation_number=row.citation_number,
        source_type=row.source_type,
        source_entity_id=row.source_entity_id,
        source_title=row.source_title,
        source_version=int(row.source_version),
        classification=row.classification,
        locator=row.locator,
        excerpt=row.excerpt,
        score=float(row.score),
    )


def _run_response(session: Session, row: SupportAIRunRow) -> SupportAIRunResponse:
    evidence = session.scalars(
        select(SupportAIEvidenceUseRow)
        .where(
            SupportAIEvidenceUseRow.tenant_id == row.tenant_id,
            SupportAIEvidenceUseRow.run_id == row.id,
        )
        .order_by(SupportAIEvidenceUseRow.citation_number)
    ).all()
    return SupportAIRunResponse(
        id=row.id,
        ai_task_id=row.ai_task_id,
        conversation_id=row.conversation_id,
        input_message_id=row.input_message_id,
        output_message_id=row.output_message_id,
        trigger_type=row.trigger_type,
        enabled_snapshot=row.enabled_snapshot,
        status=row.status,
        question=row.question,
        visitor_locale=row.visitor_locale,
        detected_language=row.detected_language,
        normalized_query=row.normalized_query,
        answer=row.answer,
        confidence=float(row.confidence) if row.confidence is not None else None,
        handoff_reason=row.handoff_reason,
        model_display_name=row.model_display_name,
        prompt_version=row.prompt_version,
        retrieval_count=row.retrieval_count,
        decision_trace=row.decision_trace,
        error_code=row.error_code,
        error_message=row.error_message,
        evidence=[_evidence_response(item) for item in evidence],
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def list_runs(
    session: Session,
    *,
    context: RequestContext,
    page: int,
    page_size: int,
    status: str | None,
) -> SupportAIRunPageResponse:
    _require(context.permissions, "support.ai.inspect")
    predicates = [SupportAIRunRow.tenant_id == context.tenant_id]
    if status:
        predicates.append(SupportAIRunRow.status == status)
    total = int(
        session.scalar(select(func.count(SupportAIRunRow.id)).where(*predicates)) or 0
    )
    rows = session.scalars(
        select(SupportAIRunRow)
        .where(*predicates)
        .order_by(SupportAIRunRow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SupportAIRunPageResponse(
        items=[_run_response(session, row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, (total + page_size - 1) // page_size),
    )


def get_run(
    session: Session,
    *,
    context: RequestContext,
    run_id: UUID,
) -> SupportAIRunResponse:
    _require(context.permissions, "support.ai.inspect")
    row = session.scalar(
        select(SupportAIRunRow).where(
            SupportAIRunRow.tenant_id == context.tenant_id,
            SupportAIRunRow.id == run_id,
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_RUN_NOT_FOUND", "智能客服运行记录不存在。", kind="not_found"
        )
    return _run_response(session, row)


def run_test(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAITestRunRequest,
) -> SupportAIRunResponse:
    _require(context.permissions, "support.ai.test")
    if not support_ai_provider_is_configured(
        session, tenant_id=context.tenant_id
    ):
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_REQUIRED",
            "当前店铺的智能客服模型暂不可用，请联系平台服务人员。",
            kind="conflict",
        )
    run = create_test_run(
        session,
        tenant_id=context.tenant_id,
        membership_id=context.membership_id,
        question=request.question,
        locale=request.locale,
    )
    process_support_ai_run(session, run_id=run.id)
    refreshed = session.get(SupportAIRunRow, run.id)
    assert refreshed is not None
    return _run_response(session, refreshed)
