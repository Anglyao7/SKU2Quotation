from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.support_ai_knowledge import process_knowledge_ingestion
from ..services.support_ai_configuration import support_ai_inline_processing_enabled
from ..support_ai_schemas import (
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
from ..use_cases import support_ai as use_cases
from .errors import application_http_error


router = APIRouter(tags=["support-ai"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get(
    "/api/v1/system/ai-generation/settings",
    response_model=SupportAIProviderSettingsResponse,
)
def get_ai_generation_settings(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIProviderSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_provider_settings(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/api/v1/system/ai-generation/settings",
    response_model=SupportAIProviderSettingsResponse,
)
def update_ai_generation_settings(
    payload: SupportAIProviderSettingsUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIProviderSettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_provider_settings(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/ai/settings",
    response_model=SupportAISettingsResponse,
)
def get_support_ai_settings(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAISettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_settings(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/support/ai/settings",
    response_model=SupportAISettingsResponse,
)
def update_support_ai_settings(
    payload: SupportAISettingsUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAISettingsResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_settings(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/ai/knowledge/sources",
    response_model=list[SupportAIKnowledgeSourceResponse],
)
def list_support_ai_knowledge_sources(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> list[SupportAIKnowledgeSourceResponse]:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_knowledge_sources(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/ai/knowledge/sources/upload",
    response_model=SupportAIKnowledgeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_support_ai_knowledge_source(
    background_tasks: BackgroundTasks,
    title: str = Form(default="", max_length=300),
    description: str | None = Form(default=None, max_length=4000),
    classification: Literal["PUBLIC", "CUSTOMER_APPROVED"] = Form(
        default="CUSTOMER_APPROVED"
    ),
    language: str = Form(default="und", min_length=2, max_length=35),
    file: UploadFile = File(...),
    session: Session = Depends(get_authenticated_session),
) -> SupportAIKnowledgeUploadResponse:
    context = current_context(session)
    content = await file.read(use_cases.MAX_KNOWLEDGE_FILE_BYTES + 1)
    try:
        result = use_cases.upload_knowledge_source(
            session,
            context=context,
            title=title,
            description=description,
            classification=classification,
            language=language,
            filename=file.filename,
            declared_content_type=file.content_type,
            content=content,
        )
        if support_ai_inline_processing_enabled():
            background_tasks.add_task(
                process_knowledge_ingestion,
                tenant_id=context.tenant_id,
                source_id=result.source.id,
                job_id=result.job.id,
            )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/api/v1/support/ai/knowledge/sources/{source_id}",
    response_model=SupportAIKnowledgeSourceResponse,
)
def update_support_ai_knowledge_source(
    source_id: UUID,
    payload: SupportAIKnowledgeSourceUpdate,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIKnowledgeSourceResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.update_knowledge_source(
            session,
            context=context,
            source_id=source_id,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/ai/knowledge/sources/{source_id}/approve",
    response_model=SupportAIKnowledgeSourceResponse,
)
def approve_support_ai_knowledge_source(
    source_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIKnowledgeSourceResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.approve_knowledge_source(
            session,
            context=context,
            source_id=source_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/api/v1/support/ai/knowledge/sources/{source_id}",
    response_model=SupportAIKnowledgeSourceResponse,
)
def revoke_support_ai_knowledge_source(
    source_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIKnowledgeSourceResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.revoke_knowledge_source(
            session,
            context=context,
            source_id=source_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/ai/knowledge/sources/{source_id}/reindex",
    response_model=SupportAIIngestionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reindex_support_ai_knowledge_source(
    source_id: UUID,
    background_tasks: BackgroundTasks,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIIngestionJobResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        result = use_cases.reindex_knowledge_source(
            session,
            context=context,
            source_id=source_id,
        )
        if result.status == "QUEUED" and support_ai_inline_processing_enabled():
            background_tasks.add_task(
                process_knowledge_ingestion,
                tenant_id=context.tenant_id,
                source_id=source_id,
                job_id=result.id,
            )
        return result
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/ai/knowledge/jobs/{job_id}",
    response_model=SupportAIIngestionJobResponse,
)
def get_support_ai_ingestion_job(
    job_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIIngestionJobResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_ingestion_job(
            session,
            context=context,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/api/v1/support/ai/test-runs",
    response_model=SupportAIRunResponse,
)
def run_support_ai_test(
    payload: SupportAITestRunRequest,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIRunResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.run_test(session, context=context, request=payload)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/ai/runs",
    response_model=SupportAIRunPageResponse,
)
def list_support_ai_runs(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    run_status: str | None = Query(default=None, alias="status", max_length=30),
    session: Session = Depends(get_authenticated_session),
) -> SupportAIRunPageResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.list_runs(
            session,
            context=context,
            page=page,
            page_size=page_size,
            status=run_status,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/api/v1/support/ai/runs/{run_id}",
    response_model=SupportAIRunResponse,
)
def get_support_ai_run(
    run_id: UUID,
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SupportAIRunResponse:
    response.headers.update(NO_STORE_HEADERS)
    context = current_context(session)
    try:
        return use_cases.get_run(session, context=context, run_id=run_id)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
