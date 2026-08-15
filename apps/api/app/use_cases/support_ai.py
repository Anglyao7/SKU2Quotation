from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    SupportAIAgentRow,
    SupportAIEvidenceUseRow,
    SupportAIIngestionJobRow,
    SupportAIKnowledgeBaseRow,
    SupportAIKnowledgeChunkRow,
    SupportAIKnowledgeSourceRow,
    SupportAIProviderSettingsRow,
    SupportAIRunRow,
    SupportAISettingsRow,
    SupportAITrainingVersionRow,
)
from ..support_ai_schemas import (
    SupportAIAgentCreate,
    SupportAIAgentKnowledgeSourceResponse,
    SupportAIAgentKnowledgeUploadItem,
    SupportAIAgentKnowledgeUploadResponse,
    SupportAIAgentResponse,
    SupportAIAgentStoreResponse,
    SupportAIAgentUpdate,
    SupportAIEvidenceResponse,
    SupportAIIngestionJobResponse,
    SupportAIKnowledgeBaseCreate,
    SupportAIKnowledgeBaseResponse,
    SupportAIKnowledgeBaseSourceResponse,
    SupportAIKnowledgeBaseSourceDetailResponse,
    SupportAIKnowledgeChunkResponse,
    SupportAIKnowledgeBaseUpdate,
    SupportAIKnowledgeBaseUploadResponse,
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
SUPPORTED_KNOWLEDGE_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".json"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
}


def _normalized_handoff_messages(value: object) -> dict[str, str]:
    """Return a stable locale/message map, including legacy JSON strings.

    An earlier SQLite backfill could serialize an already-serialized JSON
    object a second time. Keep reads resilient while normalizing every later
    write back to a regular JSON object.
    """

    candidate = value
    for _attempt in range(2):
        if isinstance(candidate, Mapping):
            return {
                str(key): str(message)
                for key, message in candidate.items()
                if str(key).strip() and str(message).strip()
            }
        if not isinstance(candidate, str):
            break
        try:
            candidate = json.loads(candidate)
        except (TypeError, ValueError):
            break
    return {}


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def require_platform_admin(context: RequestContext) -> None:
    """Public guard for routes that must reject before reading large request bodies."""

    _require_platform_admin(context)


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


def _admin_target_tenant(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID | None,
) -> TenantRow:
    """Resolve a store only after enforcing the platform administration boundary."""

    _require_platform_admin(context)
    return _platform_tenant(
        session,
        tenant_id=tenant_id or context.tenant_id,
    )


def _support_agent(session: Session, *, agent_id: UUID) -> SupportAIAgentRow:
    row = session.scalar(
        select(SupportAIAgentRow).where(SupportAIAgentRow.id == agent_id)
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_AGENT_NOT_FOUND",
            "智能体不存在。",
            kind="not_found",
        )
    return row


def _new_agent_code(session: Session) -> str:
    for _attempt in range(100):
        code = str(secrets.randbelow(90_000_000) + 10_000_000)
        exists = session.scalar(
            select(SupportAIAgentRow.id)
            .execution_options(include_deleted=True)
            .where(SupportAIAgentRow.agent_code == code)
        )
        if exists is None:
            return code
    raise ApplicationError(
        "SUPPORT_AI_AGENT_CODE_EXHAUSTED",
        "暂时无法生成智能体 ID，请重试。",
        kind="unavailable",
    )


def _agent_scope_maps(
    session: Session,
    *,
    context: RequestContext,
) -> tuple[
    dict[UUID, list[SupportAIAgentStoreResponse]],
    dict[UUID, int],
    dict[UUID, int],
]:
    stores: dict[UUID, list[SupportAIAgentStoreResponse]] = {}
    source_hashes: dict[UUID, set[str]] = {}
    approved_hashes: dict[UUID, set[str]] = {}
    tenants = session.scalars(
        select(TenantRow)
        .where(TenantRow.deleted_at.is_(None), TenantRow.status != "archived")
        .order_by(TenantRow.name, TenantRow.id)
    ).all()
    for tenant in tenants:
        with _tenant_scope(session, context=context, tenant=tenant):
            settings = get_support_ai_settings(
                session,
                tenant_id=tenant.id,
                create=False,
            )
            if settings is None or settings.agent_id is None:
                continue
            agent_id = settings.agent_id
            stores.setdefault(agent_id, []).append(
                SupportAIAgentStoreResponse(
                    tenant_id=tenant.id,
                    tenant_name=tenant.name,
                )
            )
            sources = session.execute(
                select(
                    SupportAIKnowledgeSourceRow.sha256,
                    SupportAIKnowledgeSourceRow.status,
                    SupportAIKnowledgeSourceRow.original_filename,
                ).where(
                    SupportAIKnowledgeSourceRow.tenant_id == tenant.id,
                    SupportAIKnowledgeSourceRow.agent_id == agent_id,
                )
            ).all()
            for sha256, status, original_filename in sources:
                source_hashes.setdefault(agent_id, set()).add(sha256)
                if status == "APPROVED" or (
                    status == "READY"
                    and not str(original_filename or "").casefold().endswith(".json")
                ):
                    approved_hashes.setdefault(agent_id, set()).add(sha256)
    return (
        stores,
        {agent_id: len(values) for agent_id, values in source_hashes.items()},
        {agent_id: len(values) for agent_id, values in approved_hashes.items()},
    )


def _knowledge_base_counts(
    session: Session,
) -> dict[UUID, tuple[int, int]]:
    rows = session.execute(
        select(
            SupportAIKnowledgeBaseRow.agent_id,
            func.count(SupportAIKnowledgeBaseRow.id),
            func.sum(
                case(
                    (SupportAIKnowledgeBaseRow.status == "ACTIVE", 1),
                    else_=0,
                )
            ),
        )
        .where(SupportAIKnowledgeBaseRow.deleted_at.is_(None))
        .group_by(SupportAIKnowledgeBaseRow.agent_id)
    ).all()
    return {
        agent_id: (int(total or 0), int(active or 0))
        for agent_id, total, active in rows
    }


def _agent_response(
    session: Session,
    *,
    row: SupportAIAgentRow,
    stores: list[SupportAIAgentStoreResponse],
    knowledge_base_count: int,
    active_knowledge_base_count: int,
    knowledge_source_count: int,
    approved_knowledge_source_count: int,
) -> SupportAIAgentResponse:
    snapshot = (
        support_ai_provider_snapshot(session, profile_id=row.provider_setting_id)
        if row.provider_setting_id
        else None
    )
    return SupportAIAgentResponse(
        id=row.id,
        agent_code=row.agent_code,
        name=row.name,
        description=row.description,
        enabled=row.enabled,
        provider_profile_id=row.provider_setting_id,
        model_display_name=snapshot.display_model_name if snapshot else None,
        api_configured=bool(
            row.provider_setting_id
            and support_ai_provider_is_configured(
                session,
                profile_id=row.provider_setting_id,
            )
        ),
        sku_knowledge_enabled=row.sku_knowledge_enabled,
        file_knowledge_enabled=row.file_knowledge_enabled,
        multilingual_enabled=row.multilingual_enabled,
        min_retrieval_score=float(row.min_retrieval_score),
        min_answer_confidence=float(row.min_answer_confidence),
        max_sources=row.max_sources,
        daily_auto_reply_limit=row.daily_auto_reply_limit,
        public_company_introduction=row.public_company_introduction,
        public_service_scope=row.public_service_scope,
        system_prompt=row.system_prompt,
        handoff_messages=_normalized_handoff_messages(row.handoff_messages),
        stores=stores,
        knowledge_base_count=knowledge_base_count,
        active_knowledge_base_count=active_knowledge_base_count,
        knowledge_source_count=knowledge_source_count,
        approved_knowledge_source_count=approved_knowledge_source_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_agents(
    session: Session,
    *,
    context: RequestContext,
) -> list[SupportAIAgentResponse]:
    _require_platform_admin(context)
    rows = session.scalars(
        select(SupportAIAgentRow).order_by(
            SupportAIAgentRow.updated_at.desc(),
            SupportAIAgentRow.created_at.desc(),
        )
    ).all()
    stores, source_counts, approved_counts = _agent_scope_maps(
        session,
        context=context,
    )
    knowledge_base_counts = _knowledge_base_counts(session)
    return [
        _agent_response(
            session,
            row=row,
            stores=stores.get(row.id, []),
            knowledge_base_count=knowledge_base_counts.get(row.id, (0, 0))[0],
            active_knowledge_base_count=knowledge_base_counts.get(row.id, (0, 0))[1],
            knowledge_source_count=source_counts.get(row.id, 0),
            approved_knowledge_source_count=approved_counts.get(row.id, 0),
        )
        for row in rows
    ]


def get_agent(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
) -> SupportAIAgentResponse:
    _require_platform_admin(context)
    row = _support_agent(session, agent_id=agent_id)
    stores, source_counts, approved_counts = _agent_scope_maps(
        session,
        context=context,
    )
    knowledge_base_counts = _knowledge_base_counts(session)
    return _agent_response(
        session,
        row=row,
        stores=stores.get(row.id, []),
        knowledge_base_count=knowledge_base_counts.get(row.id, (0, 0))[0],
        active_knowledge_base_count=knowledge_base_counts.get(row.id, (0, 0))[1],
        knowledge_source_count=source_counts.get(row.id, 0),
        approved_knowledge_source_count=approved_counts.get(row.id, 0),
    )


def _copy_agent_policy_to_store(
    session: Session,
    settings: SupportAISettingsRow,
    *,
    agent: SupportAIAgentRow,
    user_id: UUID,
) -> None:
    settings.agent_id = agent.id
    settings.provider_setting_id = agent.provider_setting_id
    settings.sku_knowledge_enabled = agent.sku_knowledge_enabled
    settings.file_knowledge_enabled = agent.file_knowledge_enabled
    settings.multilingual_enabled = agent.multilingual_enabled
    settings.min_retrieval_score = agent.min_retrieval_score
    settings.min_answer_confidence = agent.min_answer_confidence
    settings.max_sources = agent.max_sources
    settings.daily_auto_reply_limit = agent.daily_auto_reply_limit
    settings.public_company_introduction = agent.public_company_introduction
    settings.public_service_scope = agent.public_service_scope
    settings.system_prompt = agent.system_prompt
    settings.handoff_messages = _normalized_handoff_messages(
        agent.handoff_messages
    )
    active_training = session.scalar(
        select(SupportAITrainingVersionRow)
        .where(
            SupportAITrainingVersionRow.agent_id == agent.id,
            SupportAITrainingVersionRow.status == "PUBLISHED",
        )
        .order_by(SupportAITrainingVersionRow.version_number.desc())
    )
    settings.training_version_id = active_training.id if active_training else None
    settings.training_prompt = (
        active_training.compiled_prompt if active_training else None
    )
    settings.training_package_hash = (
        active_training.package_hash if active_training else None
    )
    settings.training_examples = (
        list(active_training.case_snapshot or []) if active_training else []
    )
    settings.prompt_version += 1
    settings.updated_by_user_id = user_id
    settings.updated_at = utcnow()
    settings.enabled = bool(
        agent.enabled
        and agent.provider_setting_id
        and support_ai_provider_is_configured(
            session,
            profile_id=agent.provider_setting_id,
        )
    )


def _sync_agent_bindings(
    session: Session,
    *,
    context: RequestContext,
    agent: SupportAIAgentRow,
    tenant_ids: list[UUID],
) -> None:
    target_ids = set(dict.fromkeys(tenant_ids))
    target_tenants = {
        tenant_id: _platform_tenant(session, tenant_id=tenant_id)
        for tenant_id in target_ids
    }
    tenants = session.scalars(
        select(TenantRow).where(
            TenantRow.deleted_at.is_(None),
            TenantRow.status != "archived",
        )
    ).all()
    for tenant in tenants:
        with _tenant_scope(session, context=context, tenant=tenant):
            settings = get_support_ai_settings(
                session,
                tenant_id=tenant.id,
                create=tenant.id in target_tenants,
            )
            if settings is None:
                continue
            if tenant.id in target_tenants:
                _copy_agent_policy_to_store(
                    session,
                    settings,
                    agent=agent,
                    user_id=context.user_id,
                )
            elif settings.agent_id == agent.id:
                settings.agent_id = None
                settings.enabled = False
                settings.training_version_id = None
                settings.training_prompt = None
                settings.training_package_hash = None
                settings.training_examples = []
                settings.updated_by_user_id = context.user_id
                settings.updated_at = utcnow()
            session.flush()


def create_agent(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAIAgentCreate,
) -> SupportAIAgentResponse:
    _require_platform_admin(context)
    _validate_profile_binding(
        session,
        profile_id=request.provider_profile_id,
    )
    row = SupportAIAgentRow(
        id=uuid4(),
        agent_code=_new_agent_code(session),
        name=request.name,
        description=request.description,
        enabled=False,
        provider_setting_id=request.provider_profile_id,
        created_by_user_id=context.user_id,
        updated_by_user_id=context.user_id,
    )
    session.add(row)
    try:
        session.flush()
        _sync_agent_bindings(
            session,
            context=context,
            agent=row,
            tenant_ids=request.tenant_ids,
        )
        session.commit()
        return get_agent(session, context=context, agent_id=row.id)
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_AGENT_CREATE_CONFLICT",
            "智能体创建失败，请重试。",
            kind="conflict",
        ) from exc


def update_agent(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    request: SupportAIAgentUpdate,
) -> SupportAIAgentResponse:
    _require_platform_admin(context)
    row = _support_agent(session, agent_id=agent_id)
    fields = request.model_fields_set
    if "name" in fields:
        if request.name is None:
            raise ApplicationError(
                "SUPPORT_AI_AGENT_NAME_REQUIRED",
                "请填写智能体名称。",
            )
        row.name = request.name
    if "description" in fields:
        row.description = request.description
    if "provider_profile_id" in fields:
        _validate_profile_binding(
            session,
            profile_id=request.provider_profile_id,
        )
        row.provider_setting_id = request.provider_profile_id
    if "enabled" in fields and request.enabled is not None:
        row.enabled = request.enabled
    for field in (
        "sku_knowledge_enabled",
        "file_knowledge_enabled",
        "multilingual_enabled",
        "max_sources",
        "daily_auto_reply_limit",
    ):
        if field in fields:
            value = getattr(request, field)
            if value is not None:
                setattr(row, field, value)
    for field in ("min_retrieval_score", "min_answer_confidence"):
        if field in fields:
            value = getattr(request, field)
            if value is not None:
                setattr(row, field, Decimal(str(value)))
    for field in ("public_company_introduction", "public_service_scope"):
        if field in fields:
            setattr(row, field, getattr(request, field))
    if "system_prompt" in fields:
        row.system_prompt = request.system_prompt
    if "handoff_messages" in fields:
        row.handoff_messages = dict(request.handoff_messages or {})
    if row.enabled and not (
        row.provider_setting_id
        and support_ai_provider_is_configured(
            session,
            profile_id=row.provider_setting_id,
        )
    ):
        raise ApplicationError(
            "SUPPORT_AI_AGENT_PROVIDER_REQUIRED",
            "启用智能体前请先完成模型 API 配置。",
            kind="conflict",
        )
    current = get_agent(session, context=context, agent_id=row.id)
    tenant_ids = (
        request.tenant_ids
        if "tenant_ids" in fields and request.tenant_ids is not None
        else [store.tenant_id for store in current.stores]
    )
    row.updated_by_user_id = context.user_id
    row.updated_at = utcnow()
    try:
        session.flush()
        _sync_agent_bindings(
            session,
            context=context,
            agent=row,
            tenant_ids=tenant_ids,
        )
        session.commit()
        return get_agent(session, context=context, agent_id=row.id)
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_AGENT_UPDATE_CONFLICT",
            "智能体保存失败，请重试。",
            kind="conflict",
        ) from exc


def _knowledge_base(
    session: Session,
    *,
    tenant_id: UUID,
    knowledge_base_id: UUID,
) -> SupportAIKnowledgeBaseRow:
    row = session.scalar(
        select(SupportAIKnowledgeBaseRow).where(
            SupportAIKnowledgeBaseRow.tenant_id == tenant_id,
            SupportAIKnowledgeBaseRow.id == knowledge_base_id,
            SupportAIKnowledgeBaseRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_BASE_NOT_FOUND",
            "知识库不存在。",
            kind="not_found",
        )
    return row


def _knowledge_base_response(
    session: Session,
    *,
    row: SupportAIKnowledgeBaseRow,
    tenant_name: str,
) -> SupportAIKnowledgeBaseResponse:
    source_count = int(
        session.scalar(
            select(func.count(SupportAIKnowledgeSourceRow.id)).where(
                SupportAIKnowledgeSourceRow.tenant_id == row.tenant_id,
                SupportAIKnowledgeSourceRow.knowledge_base_id == row.id,
                SupportAIKnowledgeSourceRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    approved_source_count = int(
        session.scalar(
            select(func.count(SupportAIKnowledgeSourceRow.id)).where(
                SupportAIKnowledgeSourceRow.tenant_id == row.tenant_id,
                SupportAIKnowledgeSourceRow.knowledge_base_id == row.id,
                SupportAIKnowledgeSourceRow.status == "APPROVED",
                SupportAIKnowledgeSourceRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    return SupportAIKnowledgeBaseResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        tenant_name=tenant_name,
        agent_id=row.agent_id,
        name=row.name,
        description=row.description,
        rules_context=row.rules_context,
        status=row.status,
        source_count=source_count,
        approved_source_count=approved_source_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_agent_knowledge_bases(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
) -> list[SupportAIKnowledgeBaseResponse]:
    _require_platform_admin(context)
    _support_agent(session, agent_id=agent_id)
    stores, _source_counts, _approved_counts = _agent_scope_maps(
        session,
        context=context,
    )
    result: list[SupportAIKnowledgeBaseResponse] = []
    for store in stores.get(agent_id, []):
        tenant = _platform_tenant(session, tenant_id=store.tenant_id)
        with _tenant_scope(session, context=context, tenant=tenant):
            rows = session.scalars(
                select(SupportAIKnowledgeBaseRow)
                .where(
                    SupportAIKnowledgeBaseRow.tenant_id == tenant.id,
                    SupportAIKnowledgeBaseRow.agent_id == agent_id,
                    SupportAIKnowledgeBaseRow.deleted_at.is_(None),
                )
                .order_by(
                    SupportAIKnowledgeBaseRow.updated_at.desc(),
                    SupportAIKnowledgeBaseRow.created_at.desc(),
                )
            ).all()
            result.extend(
                _knowledge_base_response(
                    session,
                    row=row,
                    tenant_name=tenant.name,
                )
                for row in rows
            )
    return sorted(result, key=lambda item: item.updated_at, reverse=True)


def create_agent_knowledge_base(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    request: SupportAIKnowledgeBaseCreate,
) -> SupportAIKnowledgeBaseResponse:
    _require_platform_admin(context)
    _support_agent(session, agent_id=agent_id)
    tenant = _platform_tenant(session, tenant_id=request.tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        settings = get_support_ai_settings(
            session,
            tenant_id=tenant.id,
            create=False,
        )
        if settings is None or settings.agent_id != agent_id:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_BASE_AGENT_STORE_MISMATCH",
                "只能为该智能体已绑定的店铺创建知识库。",
                kind="conflict",
            )
        row = SupportAIKnowledgeBaseRow(
            id=uuid4(),
            tenant_id=tenant.id,
            agent_id=agent_id,
            name=request.name,
            description=request.description,
            rules_context=request.rules_context,
            status="ACTIVE",
            created_by_user_id=context.user_id,
            updated_by_user_id=context.user_id,
        )
        session.add(row)
        try:
            session.flush()
            response = _knowledge_base_response(
                session,
                row=row,
                tenant_name=tenant.name,
            )
            session.commit()
            return response
        except IntegrityError as exc:
            session.rollback()
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_BASE_NAME_CONFLICT",
                "该店铺下已经存在同名知识库。",
                kind="conflict",
            ) from exc


def update_knowledge_base(
    session: Session,
    *,
    context: RequestContext,
    knowledge_base_id: UUID,
    request: SupportAIKnowledgeBaseUpdate,
    tenant_id: UUID,
) -> SupportAIKnowledgeBaseResponse:
    _require_platform_admin(context)
    tenant = _platform_tenant(session, tenant_id=tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        row = _knowledge_base(
            session,
            tenant_id=tenant.id,
            knowledge_base_id=knowledge_base_id,
        )
        if request.name is not None:
            row.name = request.name
        if "description" in request.model_fields_set:
            row.description = request.description
        if "rules_context" in request.model_fields_set:
            row.rules_context = request.rules_context
        if request.status is not None:
            row.status = request.status
        row.updated_by_user_id = context.user_id
        row.updated_at = utcnow()
        try:
            session.flush()
            response = _knowledge_base_response(
                session,
                row=row,
                tenant_name=tenant.name,
            )
            session.commit()
            return response
        except IntegrityError as exc:
            session.rollback()
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_BASE_NAME_CONFLICT",
                "该店铺下已经存在同名知识库。",
                kind="conflict",
            ) from exc


def list_knowledge_base_sources(
    session: Session,
    *,
    context: RequestContext,
    knowledge_base_id: UUID,
    tenant_id: UUID,
) -> list[SupportAIKnowledgeBaseSourceResponse]:
    _require_platform_admin(context)
    tenant = _platform_tenant(session, tenant_id=tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        base = _knowledge_base(
            session,
            tenant_id=tenant.id,
            knowledge_base_id=knowledge_base_id,
        )
        rows = session.scalars(
            select(SupportAIKnowledgeSourceRow)
            .where(
                SupportAIKnowledgeSourceRow.tenant_id == tenant.id,
                SupportAIKnowledgeSourceRow.knowledge_base_id == base.id,
                SupportAIKnowledgeSourceRow.deleted_at.is_(None),
            )
            .order_by(SupportAIKnowledgeSourceRow.created_at.desc())
        ).all()
        return [
            SupportAIKnowledgeBaseSourceResponse(
                knowledge_base_id=base.id,
                knowledge_base_name=base.name,
                source=_source_response(row),
            )
            for row in rows
        ]


def get_knowledge_base_source_detail(
    session: Session,
    *,
    context: RequestContext,
    knowledge_base_id: UUID,
    source_id: UUID,
    tenant_id: UUID,
) -> SupportAIKnowledgeBaseSourceDetailResponse:
    """Return the committed parser output for one file in a knowledge base."""

    _require_platform_admin(context)
    tenant = _platform_tenant(session, tenant_id=tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        base = _knowledge_base(
            session,
            tenant_id=tenant.id,
            knowledge_base_id=knowledge_base_id,
        )
        source = session.scalar(
            select(SupportAIKnowledgeSourceRow).where(
                SupportAIKnowledgeSourceRow.tenant_id == tenant.id,
                SupportAIKnowledgeSourceRow.id == source_id,
                SupportAIKnowledgeSourceRow.knowledge_base_id == base.id,
                SupportAIKnowledgeSourceRow.deleted_at.is_(None),
            )
        )
        if source is None:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_SOURCE_NOT_FOUND",
                "知识文件不存在。",
                kind="not_found",
            )
        chunks = session.scalars(
            select(SupportAIKnowledgeChunkRow)
            .where(
                SupportAIKnowledgeChunkRow.tenant_id == tenant.id,
                SupportAIKnowledgeChunkRow.source_id == source.id,
                SupportAIKnowledgeChunkRow.status == "ACTIVE",
            )
            .order_by(SupportAIKnowledgeChunkRow.chunk_index)
        ).all()
        return SupportAIKnowledgeBaseSourceDetailResponse(
            knowledge_base_id=base.id,
            knowledge_base_name=base.name,
            source=_source_response(source),
            chunks=[
                SupportAIKnowledgeChunkResponse(
                    id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    section_path=chunk.section_path,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    language=chunk.language,
                    locator=dict(chunk.locator or {}),
                )
                for chunk in chunks
            ],
        )


def upload_knowledge_base_source(
    session: Session,
    *,
    context: RequestContext,
    knowledge_base_id: UUID,
    tenant_id: UUID,
    title: str,
    description: str | None,
    classification: str,
    language: str,
    filename: str | None,
    declared_content_type: str | None,
    content: bytes,
    knowledge_type: str = "MERCHANT_PROFILE",
) -> SupportAIKnowledgeBaseUploadResponse:
    _require_platform_admin(context)
    suffix = Path(filename or "").suffix.casefold()
    allowed_by_type = {
        "QA_STRATEGY": {".json"},
        "MERCHANT_PROFILE": {".md", ".docx", ".txt"},
    }
    allowed_extensions = allowed_by_type.get(knowledge_type)
    if allowed_extensions is None:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TYPE_INVALID",
            "知识文件类型无效。",
            kind="validation",
        )
    if suffix not in allowed_extensions:
        labels = "JSON" if knowledge_type == "QA_STRATEGY" else "MD、DOCX 或 TXT"
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TYPE_MISMATCH",
            f"{('问答策略' if knowledge_type == 'QA_STRATEGY' else '商家背景资料')}只接受 {labels} 文件。",
            kind="validation",
        )
    tenant = _platform_tenant(session, tenant_id=tenant_id)
    with _tenant_scope(session, context=context, tenant=tenant):
        base = _knowledge_base(
            session,
            tenant_id=tenant.id,
            knowledge_base_id=knowledge_base_id,
        )
        uploaded = _upload_knowledge_source_in_scope(
            session,
            tenant_id=tenant.id,
            agent_id=base.agent_id,
            knowledge_base_id=base.id,
            requested_by_user_id=context.user_id,
            title=title,
            description=description,
            classification=classification,
            language=language,
            filename=filename,
            declared_content_type=declared_content_type,
            content=content,
        )
        return SupportAIKnowledgeBaseUploadResponse(
            knowledge_base=_knowledge_base_response(
                session,
                row=base,
                tenant_name=tenant.name,
            ),
            source=uploaded.source,
            job=uploaded.job,
        )


def list_agent_knowledge_sources(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
) -> list[SupportAIAgentKnowledgeSourceResponse]:
    _require_platform_admin(context)
    _support_agent(session, agent_id=agent_id)
    stores, _source_counts, _approved_counts = _agent_scope_maps(
        session,
        context=context,
    )
    result: list[SupportAIAgentKnowledgeSourceResponse] = []
    for store in stores.get(agent_id, []):
        tenant = _platform_tenant(session, tenant_id=store.tenant_id)
        with _tenant_scope(session, context=context, tenant=tenant):
            rows = session.scalars(
                select(SupportAIKnowledgeSourceRow)
                .where(
                    SupportAIKnowledgeSourceRow.tenant_id == tenant.id,
                    SupportAIKnowledgeSourceRow.agent_id == agent_id,
                )
                .order_by(SupportAIKnowledgeSourceRow.created_at.desc())
            ).all()
            result.extend(
                SupportAIAgentKnowledgeSourceResponse(
                    tenant_id=tenant.id,
                    tenant_name=tenant.name,
                    source=_source_response(row),
                )
                for row in rows
            )
    return sorted(
        result,
        key=lambda item: item.source.created_at,
        reverse=True,
    )


def upload_agent_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    agent_id: UUID,
    title: str,
    description: str | None,
    classification: str,
    language: str,
    filename: str | None,
    declared_content_type: str | None,
    content: bytes,
) -> SupportAIAgentKnowledgeUploadResponse:
    _require_platform_admin(context)
    _support_agent(session, agent_id=agent_id)
    stores, _source_counts, _approved_counts = _agent_scope_maps(
        session,
        context=context,
    )
    bound_stores = stores.get(agent_id, [])
    if not bound_stores:
        raise ApplicationError(
            "SUPPORT_AI_AGENT_STORE_REQUIRED",
            "请先为智能体绑定至少一个店铺，再上传知识库。",
            kind="conflict",
        )
    items: list[SupportAIAgentKnowledgeUploadItem] = []
    for store in bound_stores:
        tenant = _platform_tenant(session, tenant_id=store.tenant_id)
        with _tenant_scope(session, context=context, tenant=tenant):
            knowledge_base = _get_or_create_default_knowledge_base(
                session,
                tenant=tenant,
                agent_id=agent_id,
                requested_by_user_id=context.user_id,
            )
            uploaded = _upload_knowledge_source_in_scope(
                session,
                tenant_id=tenant.id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base.id,
                requested_by_user_id=context.user_id,
                title=title,
                description=description,
                classification=classification,
                language=language,
                filename=filename,
                declared_content_type=declared_content_type,
                content=content,
            )
        items.append(
            SupportAIAgentKnowledgeUploadItem(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                source=uploaded.source,
                job=uploaded.job,
            )
        )
    return SupportAIAgentKnowledgeUploadResponse(items=items)


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
            "public_company_introduction": source.public_company_introduction,
            "public_service_scope": source.public_service_scope,
            "system_prompt": source.system_prompt,
            "handoff_messages": _normalized_handoff_messages(
                source.handoff_messages
            ),
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
                    "public_company_introduction",
                    "public_service_scope",
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
                SupportAIKnowledgeSourceRow.status.in_(["READY", "APPROVED"]),
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
        public_company_introduction=row.public_company_introduction,
        public_service_scope=row.public_service_scope,
        system_prompt=row.system_prompt,
        handoff_messages=_normalized_handoff_messages(row.handoff_messages),
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
    tenant_id: UUID | None = None,
) -> SupportAISettingsResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        response = _settings_response(session, tenant_id=tenant.id)
    session.commit()
    return response


def update_settings(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAISettingsUpdate,
    tenant_id: UUID | None = None,
) -> SupportAISettingsResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        if request.enabled and not support_ai_provider_is_configured(
            session, tenant_id=tenant.id
        ):
            raise ApplicationError(
                "SUPPORT_AI_PROVIDER_REQUIRED",
                "当前店铺的智能客服模型暂不可用，请先在配置中心分配模型。",
                kind="conflict",
            )
        row = get_support_ai_settings(session, tenant_id=tenant.id, create=True)
        assert row is not None
        row.enabled = request.enabled
        row.sku_knowledge_enabled = request.sku_knowledge_enabled
        row.file_knowledge_enabled = request.file_knowledge_enabled
        row.multilingual_enabled = request.multilingual_enabled
        row.min_retrieval_score = request.min_retrieval_score
        row.min_answer_confidence = request.min_answer_confidence
        row.max_sources = request.max_sources
        row.daily_auto_reply_limit = request.daily_auto_reply_limit
        row.public_company_introduction = request.public_company_introduction
        row.public_service_scope = request.public_service_scope
        row.system_prompt = request.system_prompt
        row.handoff_messages = request.handoff_messages
        row.prompt_version += 1
        row.updated_by_user_id = context.user_id
        row.updated_at = utcnow()
        session.flush()
        response = _settings_response(session, tenant_id=tenant.id)
    session.commit()
    return response


def _source_response(row: SupportAIKnowledgeSourceRow) -> SupportAIKnowledgeSourceResponse:
    return SupportAIKnowledgeSourceResponse(
        id=row.id,
        knowledge_base_id=row.knowledge_base_id,
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
    tenant_id: UUID | None = None,
) -> list[SupportAIKnowledgeSourceResponse]:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        rows = session.scalars(
            select(SupportAIKnowledgeSourceRow)
            .where(SupportAIKnowledgeSourceRow.tenant_id == tenant.id)
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
    tenant_id: UUID | None = None,
    title: str,
    description: str | None,
    classification: str,
    language: str,
    filename: str | None,
    declared_content_type: str | None,
    content: bytes,
) -> SupportAIKnowledgeUploadResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        settings = get_support_ai_settings(
            session,
            tenant_id=tenant.id,
            create=True,
        )
        assert settings is not None
        agent_id = settings.agent_id
        if agent_id is None:
            # Compatibility for the original tenant-scoped upload endpoint:
            # materialize the tenant's current policy as its first agent and
            # then create the required knowledge base under that agent.
            agent = SupportAIAgentRow(
                id=uuid4(),
                agent_code=_new_agent_code(session),
                name=f"{tenant.name} 智能客服"[:160],
                enabled=False,
                # The legacy tenant endpoint keeps its provider binding on
                # support_ai_settings; leave the compatibility agent detached
                # so deleting that legacy provider profile remains safe.
                provider_setting_id=None,
                sku_knowledge_enabled=settings.sku_knowledge_enabled,
                file_knowledge_enabled=settings.file_knowledge_enabled,
                multilingual_enabled=settings.multilingual_enabled,
                min_retrieval_score=settings.min_retrieval_score,
                min_answer_confidence=settings.min_answer_confidence,
                max_sources=settings.max_sources,
                daily_auto_reply_limit=settings.daily_auto_reply_limit,
                public_company_introduction=settings.public_company_introduction,
                public_service_scope=settings.public_service_scope,
                system_prompt=settings.system_prompt,
                handoff_messages=_normalized_handoff_messages(
                    settings.handoff_messages
                ),
                created_by_user_id=context.user_id,
                updated_by_user_id=context.user_id,
            )
            session.add(agent)
            session.flush()
            settings.agent_id = agent.id
            settings.updated_by_user_id = context.user_id
            settings.updated_at = utcnow()
            agent_id = agent.id
        knowledge_base = _get_or_create_default_knowledge_base(
            session,
            tenant=tenant,
            agent_id=agent_id,
            requested_by_user_id=context.user_id,
        )
        return _upload_knowledge_source_in_scope(
            session,
            tenant_id=tenant.id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base.id,
            requested_by_user_id=context.user_id,
            title=title,
            description=description,
            classification=classification,
            language=language,
            filename=filename,
            declared_content_type=declared_content_type,
            content=content,
        )


def _get_or_create_default_knowledge_base(
    session: Session,
    *,
    tenant: TenantRow,
    agent_id: UUID,
    requested_by_user_id: UUID,
) -> SupportAIKnowledgeBaseRow:
    row = session.scalar(
        select(SupportAIKnowledgeBaseRow)
        .where(
            SupportAIKnowledgeBaseRow.tenant_id == tenant.id,
            SupportAIKnowledgeBaseRow.agent_id == agent_id,
            SupportAIKnowledgeBaseRow.deleted_at.is_(None),
        )
        .order_by(SupportAIKnowledgeBaseRow.created_at)
    )
    if row is not None:
        return row
    agent = _support_agent(session, agent_id=agent_id)
    row = SupportAIKnowledgeBaseRow(
        id=uuid4(),
        tenant_id=tenant.id,
        agent_id=agent_id,
        name=f"{tenant.name} · {agent.name}知识库"[:160],
        status="ACTIVE",
        created_by_user_id=requested_by_user_id,
        updated_by_user_id=requested_by_user_id,
    )
    session.add(row)
    session.flush()
    return row


def _upload_knowledge_source_in_scope(
    session: Session,
    *,
    tenant_id: UUID,
    agent_id: UUID | None,
    knowledge_base_id: UUID | None,
    requested_by_user_id: UUID,
    title: str,
    description: str | None,
    classification: str,
    language: str,
    filename: str | None,
    declared_content_type: str | None,
    content: bytes,
) -> SupportAIKnowledgeUploadResponse:
    original_filename = Path(filename or "knowledge-file").name[:500]
    suffix = Path(original_filename).suffix.casefold()
    if suffix not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TYPE_UNSUPPORTED",
            "仅支持 PDF、DOCX、TXT、Markdown 和 JSON 文件。",
        )
    if not content:
        raise ApplicationError("SUPPORT_AI_KNOWLEDGE_EMPTY", "请选择知识文件。")
    if len(content) > MAX_KNOWLEDGE_FILE_BYTES:
        raise ApplicationError(
            "SUPPORT_AI_KNOWLEDGE_TOO_LARGE",
            "单个知识文件不能超过 25 MB。",
            kind="too_large",
        )
    if suffix == ".json":
        try:
            json_payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_JSON_INVALID",
                "JSON 文件格式无效，请检查编码和语法。",
            ) from exc
        if (
            isinstance(json_payload, dict)
            and json_payload.get("schema_version") == "support-ai-training/v1"
        ):
            raise ApplicationError(
                "SUPPORT_AI_TRAINING_PACKAGE_REQUIRES_TRAINING_IMPORT",
                "这是智能客服案例 JSON，请在后台知识库管理中选择智能体后导入，不能作为事实知识向量化。",
                kind="conflict",
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
    object_key = f"tenants/{tenant_id}/documents/support-ai/{source_id}{suffix}"
    storage = get_object_storage()
    with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
        temporary.write(content)
        temporary.flush()
        path = Path(temporary.name)
        try:
            storage.put_file(
                path,
                object_key=object_key,
                content_type=declared_content_type or CONTENT_TYPES[suffix],
            )
        except Exception as exc:
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_STORAGE_UNAVAILABLE",
                "知识文件上传到对象存储失败，请联系平台管理员。",
                kind="unavailable",
            ) from exc
    media = MediaObjectRow(
        id=media_id,
        tenant_id=tenant_id,
        object_key=object_key,
        zone="DOCUMENT",
        original_filename=original_filename,
        sha256=sha256,
        byte_size=len(content),
        declared_media_type=declared_content_type,
        detected_media_type=CONTENT_TYPES[suffix],
        status="AVAILABLE",
        scan_status="CLEAN",
        scan_engine=None,
        scan_result={"detail_code": "SCAN_NOT_REQUIRED"},
        scan_at=None,
        retention_class="SOURCE_DEFAULT",
        created_by_user_id=requested_by_user_id,
    )
    source = SupportAIKnowledgeSourceRow(
        id=source_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
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
        created_by_user_id=requested_by_user_id,
    )
    job = SupportAIIngestionJobRow(
        id=job_id,
        tenant_id=tenant_id,
        source_id=source_id,
        status="QUEUED",
        progress=0,
        requested_by_user_id=requested_by_user_id,
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
    tenant_id: UUID | None = None,
) -> SupportAIKnowledgeSourceResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        row = _knowledge_source(
            session, tenant_id=tenant.id, source_id=source_id
        )
        if row.status == "PROCESSING":
            raise ApplicationError(
                "SUPPORT_AI_KNOWLEDGE_BUSY",
                "知识文件正在处理，请稍后再修改。",
                kind="conflict",
            )
        row.title = request.title
        row.description = request.description
        row.classification = request.classification
        row.language = request.language
        row.version += 1
        session.commit()
        return _source_response(row)


def approve_knowledge_source(
    session: Session,
    *,
    context: RequestContext,
    source_id: UUID,
    tenant_id: UUID | None = None,
) -> SupportAIKnowledgeSourceResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        row = _knowledge_source(
            session, tenant_id=tenant.id, source_id=source_id
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
    tenant_id: UUID | None = None,
) -> SupportAIKnowledgeSourceResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        row = _knowledge_source(
            session, tenant_id=tenant.id, source_id=source_id
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
    tenant_id: UUID | None = None,
) -> SupportAIIngestionJobResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        row = _knowledge_source(
            session, tenant_id=tenant.id, source_id=source_id
        )
        active_job = session.scalar(
            select(SupportAIIngestionJobRow).where(
                SupportAIIngestionJobRow.tenant_id == tenant.id,
                SupportAIIngestionJobRow.source_id == source_id,
                SupportAIIngestionJobRow.status.in_(["QUEUED", "RUNNING"]),
            )
        )
        if active_job is not None:
            return _job_response(active_job)
        job = SupportAIIngestionJobRow(
            id=uuid4(),
            tenant_id=tenant.id,
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
    tenant_id: UUID | None = None,
) -> SupportAIIngestionJobResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        row = session.scalar(
            select(SupportAIIngestionJobRow).where(
                SupportAIIngestionJobRow.tenant_id == tenant.id,
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
    training_case_ids: list[UUID] = []
    for value in row.training_case_ids or []:
        try:
            training_case_ids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
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
        training_version_id=row.training_version_id,
        training_case_ids=training_case_ids,
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
    tenant_id: UUID | None = None,
) -> SupportAIRunPageResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        predicates = [SupportAIRunRow.tenant_id == tenant.id]
        if status:
            predicates.append(SupportAIRunRow.status == status)
        total = int(
            session.scalar(select(func.count(SupportAIRunRow.id)).where(*predicates))
            or 0
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
    tenant_id: UUID | None = None,
) -> SupportAIRunResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        row = session.scalar(
            select(SupportAIRunRow).where(
                SupportAIRunRow.tenant_id == tenant.id,
                SupportAIRunRow.id == run_id,
            )
        )
        if row is None:
            raise ApplicationError(
                "SUPPORT_AI_RUN_NOT_FOUND",
                "智能客服运行记录不存在。",
                kind="not_found",
            )
        return _run_response(session, row)


def run_test(
    session: Session,
    *,
    context: RequestContext,
    request: SupportAITestRunRequest,
    tenant_id: UUID | None = None,
) -> SupportAIRunResponse:
    tenant = _admin_target_tenant(
        session,
        context=context,
        tenant_id=tenant_id,
    )
    with _tenant_scope(session, context=context, tenant=tenant):
        if not support_ai_provider_is_configured(
            session, tenant_id=tenant.id
        ):
            raise ApplicationError(
                "SUPPORT_AI_PROVIDER_REQUIRED",
                "当前店铺的智能客服模型暂不可用，请先在配置中心分配模型。",
                kind="conflict",
            )
        run = create_test_run(
            session,
            tenant_id=tenant.id,
            membership_id=(
                context.membership_id
                if tenant.id == context.tenant_id
                else None
            ),
            question=request.question,
            locale=request.locale,
        )
        process_support_ai_run(session, run_id=run.id)
        refreshed = session.get(SupportAIRunRow, run.id)
        assert refreshed is not None
        return _run_response(session, refreshed)
