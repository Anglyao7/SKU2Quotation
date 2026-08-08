from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..catalog_translation_schemas import (
    CatalogTranslationJobResponse,
    CatalogTranslationJobStartRequest,
    CatalogTranslationStatusResponse,
)
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import catalog_translations as use_cases
from .errors import application_http_error


router = APIRouter(
    prefix="/api/v1/catalog/translations",
    tags=["catalog-translations"],
)


@router.get("/status", response_model=CatalogTranslationStatusResponse)
def get_translation_status(
    target_locale: str = Query(default="en-US", max_length=20),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationStatusResponse:
    context = current_context(session)
    try:
        return use_cases.get_translation_status(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            target_locale=target_locale,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs",
    response_model=CatalogTranslationJobResponse,
    status_code=202,
)
def start_translation_job(
    payload: CatalogTranslationJobStartRequest,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="catalog-translation-jobs",
        limit=configured_limit("RATE_LIMIT_CATALOG_TRANSLATION_JOBS", 12),
        window_seconds=configured_limit(
            "RATE_LIMIT_CATALOG_TRANSLATION_JOB_WINDOW_SECONDS",
            3_600,
            maximum=86_400,
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.start_translation_job(
            session,
            context=context,
            request=payload,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/jobs/latest",
    response_model=CatalogTranslationJobResponse | None,
)
def latest_translation_job(
    target_locale: str = Query(default="en-US", max_length=20),
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse | None:
    context = current_context(session)
    try:
        return use_cases.latest_translation_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            target_locale=target_locale,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/jobs/{job_id}",
    response_model=CatalogTranslationJobResponse,
)
def get_translation_job(
    job_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        return use_cases.get_translation_job(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs/{job_id}/pause",
    response_model=CatalogTranslationJobResponse,
)
def pause_translation_job(
    job_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        return use_cases.pause_translation_job(
            session,
            context=context,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/jobs/{job_id}/resume",
    response_model=CatalogTranslationJobResponse,
)
def resume_translation_job(
    job_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> CatalogTranslationJobResponse:
    context = current_context(session)
    try:
        return use_cases.resume_translation_job(
            session,
            context=context,
            job_id=job_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
