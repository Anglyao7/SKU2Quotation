from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_session
from ..domain.errors import ApplicationError
from ..platform_admin_schemas import (
    PlatformTenantCreate,
    PlatformTenantSummary,
    PlatformTenantUpdate,
)
from ..services.auth.dependencies import RequestContext, require_request_context
from ..use_cases import platform_admin as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/admin", tags=["platform-administration"])


@router.get("/tenants", response_model=list[PlatformTenantSummary])
def tenants_endpoint(
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> list[PlatformTenantSummary]:
    try:
        return use_cases.list_tenants(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/tenants",
    response_model=PlatformTenantSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant_endpoint(
    request: PlatformTenantCreate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> PlatformTenantSummary:
    try:
        return use_cases.create_tenant(session, context=context, request=request)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/tenants/{tenant_id}", response_model=PlatformTenantSummary)
def update_tenant_endpoint(
    tenant_id: UUID,
    request: PlatformTenantUpdate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> PlatformTenantSummary:
    try:
        return use_cases.update_tenant(
            session,
            context=context,
            tenant_id=tenant_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
