from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..access_control_schemas import (
    TenantMemberRolesUpdateRequest,
    TenantMemberSummary,
    TenantPermissionSummary,
    TenantRoleCreateRequest,
    TenantRoleSummary,
    TenantRoleUpdateRequest,
)
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import access_control as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/access-control", tags=["tenant-access-control"])


@router.get("/permissions", response_model=list[TenantPermissionSummary])
def list_permissions(
    session: Session = Depends(get_authenticated_session),
) -> list[TenantPermissionSummary]:
    context = current_context(session)
    try:
        return use_cases.list_permissions(session, permissions=context.permissions)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/roles", response_model=list[TenantRoleSummary])
def list_roles(
    session: Session = Depends(get_authenticated_session),
) -> list[TenantRoleSummary]:
    context = current_context(session)
    try:
        return use_cases.list_roles(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/roles",
    response_model=TenantRoleSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_role(
    request: TenantRoleCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> TenantRoleSummary:
    context = current_context(session)
    try:
        return use_cases.create_role(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch("/roles/{role_id}", response_model=TenantRoleSummary)
def update_role(
    role_id: UUID,
    request: TenantRoleUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> TenantRoleSummary:
    context = current_context(session)
    try:
        return use_cases.update_role(
            session,
            tenant_id=context.tenant_id,
            actor_membership_id=context.membership_id,
            permissions=context.permissions,
            role_id=role_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/members", response_model=list[TenantMemberSummary])
def list_members(
    session: Session = Depends(get_authenticated_session),
) -> list[TenantMemberSummary]:
    context = current_context(session)
    try:
        return use_cases.list_members(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/members/{membership_id}/roles",
    response_model=TenantMemberSummary,
)
def update_member_roles(
    membership_id: UUID,
    request: TenantMemberRolesUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> TenantMemberSummary:
    context = current_context(session)
    try:
        return use_cases.update_member_roles(
            session,
            tenant_id=context.tenant_id,
            actor_membership_id=context.membership_id,
            actor_user_id=context.user_id,
            permissions=context.permissions,
            membership_id=membership_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
