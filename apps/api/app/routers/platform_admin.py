from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_auth_session, get_session
from ..domain.errors import ApplicationError
from ..platform_admin_schemas import (
    PlatformMemberInvitation,
    PlatformMemberInvitationCreate,
    PlatformMerchantIdentityCreate,
    PlatformMerchantIdentityProfile,
    PlatformMerchantIdentityUpdate,
    PlatformMerchantOwnerAccount,
    PlatformMerchantOwnerCreate,
    PlatformMerchantOwnerPasswordReset,
    PlatformMerchantOwnerPasswordResetResponse,
    PlatformTenantCreate,
    PlatformTenantSubscriptionUpdate,
    PlatformTenantSummary,
    PlatformTenantUpdate,
)
from ..services.auth.dependencies import RequestContext, require_request_context
from ..use_cases import platform_admin as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/admin", tags=["platform-administration"])


def _identity_write_session(session: Session, identity_session: Session) -> Session:
    """Avoid a second SQLite transaction during local account provisioning."""

    if session.bind is not None and session.bind.dialect.name == "sqlite":
        return session
    return identity_session


@router.get(
    "/merchant-identities",
    response_model=list[PlatformMerchantIdentityProfile],
)
def merchant_identities_endpoint(
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> list[PlatformMerchantIdentityProfile]:
    try:
        return use_cases.list_merchant_identities(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/merchant-identities",
    response_model=PlatformMerchantIdentityProfile,
    status_code=status.HTTP_201_CREATED,
)
def create_merchant_identity_endpoint(
    request: PlatformMerchantIdentityCreate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> PlatformMerchantIdentityProfile:
    try:
        return use_cases.create_merchant_identity(
            session,
            context=context,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/merchant-identities/{identity_code}",
    response_model=PlatformMerchantIdentityProfile,
)
def update_merchant_identity_endpoint(
    identity_code: str,
    request: PlatformMerchantIdentityUpdate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> PlatformMerchantIdentityProfile:
    try:
        return use_cases.update_merchant_identity(
            session,
            context=context,
            identity_code=identity_code,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/merchant-identities/{identity_code}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_merchant_identity_endpoint(
    identity_code: str,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> None:
    try:
        use_cases.delete_merchant_identity(
            session,
            context=context,
            identity_code=identity_code,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


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


@router.patch(
    "/tenants/{tenant_id}/subscription",
    response_model=PlatformTenantSummary,
)
def update_tenant_subscription_endpoint(
    tenant_id: UUID,
    request: PlatformTenantSubscriptionUpdate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> PlatformTenantSummary:
    try:
        return use_cases.update_tenant_subscription(
            session,
            context=context,
            tenant_id=tenant_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/tenants/{tenant_id}/owner-account",
    response_model=PlatformMerchantOwnerAccount,
    status_code=status.HTTP_201_CREATED,
)
def provision_merchant_owner_endpoint(
    tenant_id: UUID,
    request: PlatformMerchantOwnerCreate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PlatformMerchantOwnerAccount:
    try:
        return use_cases.provision_merchant_owner(
            session,
            _identity_write_session(session, identity_session),
            context=context,
            tenant_id=tenant_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/tenants/{tenant_id}/owner-account/password-reset",
    response_model=PlatformMerchantOwnerPasswordResetResponse,
)
def reset_merchant_owner_password_endpoint(
    tenant_id: UUID,
    request: PlatformMerchantOwnerPasswordReset,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PlatformMerchantOwnerPasswordResetResponse:
    try:
        return use_cases.reset_merchant_owner_password(
            session,
            _identity_write_session(session, identity_session),
            context=context,
            tenant_id=tenant_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/tenants/{tenant_id}/member-invitations",
    response_model=PlatformMemberInvitation,
    status_code=status.HTTP_201_CREATED,
)
def invite_tenant_member_endpoint(
    tenant_id: UUID,
    request: PlatformMemberInvitationCreate,
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
    identity_session: Session = Depends(get_auth_session),
) -> PlatformMemberInvitation:
    try:
        return use_cases.invite_tenant_member(
            session,
            identity_session,
            context=context,
            tenant_id=tenant_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
