from __future__ import annotations

import hashlib
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.file_scanner import get_file_scanner
from ..adapters.object_storage import get_object_storage
from ..domain.errors import ApplicationError
from ..file_security_models import MediaObjectRow
from ..knowledge_embedding_models import KnowledgeDocumentRow
from ..model_mixins import utcnow
from ..services.auth.dependencies import RequestContext
from ..services.chat_generation import ChatGenerationError
from ..services.support_ai_configuration import (
    save_managed_support_ai_provider,
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
    SupportAIRunRow,
)
from ..support_ai_schemas import (
    SupportAIEvidenceResponse,
    SupportAIIngestionJobResponse,
    SupportAIKnowledgeSourceResponse,
    SupportAIKnowledgeSourceUpdate,
    SupportAIKnowledgeUploadResponse,
    SupportAIProviderSettingsResponse,
    SupportAIProviderSettingsUpdate,
    SupportAIRunPageResponse,
    SupportAIRunResponse,
    SupportAISettingsResponse,
    SupportAISettingsUpdate,
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


def get_provider_settings(
    session: Session,
    *,
    context: RequestContext,
) -> SupportAIProviderSettingsResponse:
    _require_platform_admin(context)
    try:
        return SupportAIProviderSettingsResponse(
            **asdict(support_ai_provider_snapshot(session))
        )
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
        return SupportAIProviderSettingsResponse(
            **asdict(support_ai_provider_snapshot(session))
        )
    except (ChatGenerationError, ValueError) as exc:
        session.rollback()
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_CONFIGURATION_INVALID",
            str(exc),
        ) from exc


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
        mode=row.mode,
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
        provider_configured=support_ai_provider_is_configured(session),
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
    if request.mode != "OFF" and not support_ai_provider_is_configured(session):
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_REQUIRED",
            "请先在配置中心完成智能客服大模型 API 配置。",
            kind="conflict",
        )
    row = get_support_ai_settings(session, tenant_id=context.tenant_id, create=True)
    assert row is not None
    row.mode = request.mode
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
        mode_snapshot=row.mode_snapshot,
        status=row.status,
        question=row.question,
        visitor_locale=row.visitor_locale,
        detected_language=row.detected_language,
        normalized_query=row.normalized_query,
        answer=row.answer,
        confidence=float(row.confidence) if row.confidence is not None else None,
        handoff_reason=row.handoff_reason,
        provider=row.provider,
        model_name=row.model_name,
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
    if not support_ai_provider_is_configured(session):
        raise ApplicationError(
            "SUPPORT_AI_PROVIDER_REQUIRED",
            "请先在配置中心完成智能客服大模型 API 配置。",
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
