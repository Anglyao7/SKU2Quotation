from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..auth_schemas import (
    AuthContext,
    AuthTokenData,
    AuthTokenResponse,
    AuthUser,
    LoginRequest,
    MembershipSummary,
    MeResponse,
    PermissionResponse,
    TenantContextRequest,
)
from ..database import get_auth_session, get_session
from ..services.auth.dependencies import RequestContext, bearer, require_request_context
from ..services.auth.service import (
    AuthError,
    IssuedSession,
    active_memberships_for_access_token,
    access_ttl_seconds,
    login,
    logout,
    refresh,
    switch_tenant,
)
from ..services.auth.tokens import REFRESH_COOKIE_NAME, REFRESH_TTL_SECONDS
from ..domain.errors import ApplicationError
from ..use_cases.authentication import get_current_user
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["authentication"])


def _http_error(exc: AuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _masked_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _token_response(result: IssuedSession) -> AuthTokenResponse:
    return AuthTokenResponse(
        data=AuthTokenData(
            access_token=result.access_token,
            expires_in=access_ttl_seconds(),
            csrf_token=result.csrf_token,
            session_id=result.auth_session.id,
            requires_tenant_selection=result.requires_tenant_selection,
            user=AuthUser(
                id=result.user.id,
                display_name=result.user.display_name,
                email=_masked_email(result.user.email_normalized),
                is_platform_admin=bool(result.user.is_platform_admin),
            ),
            context=AuthContext(
                tenant_id=result.tenant.id if result.tenant else None,
                membership_id=result.membership.id if result.membership else None,
                tenant_name=result.tenant.name if result.tenant else None,
                tenant_slug=result.tenant.slug if result.tenant else None,
                default_workspace="dashboard" if result.tenant else None,
            ),
        )
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    secure = os.getenv("APP_ENV", "development").lower() in {
        "staging",
        "production",
        "prod",
    }
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=REFRESH_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def _bearer_value(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED"})
    return credentials.credentials


@router.post("/auth/login", response_model=AuthTokenResponse)
def login_endpoint(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_auth_session),
) -> AuthTokenResponse:
    try:
        result = login(
            session,
            payload,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    _set_refresh_cookie(response, result.refresh_token)
    return _token_response(result)


@router.post("/auth/refresh", response_model=AuthTokenResponse)
def refresh_endpoint(
    request: Request,
    response: Response,
    csrf_token: str = Header(alias="X-CSRF-Token"),
    session: Session = Depends(get_auth_session),
) -> AuthTokenResponse:
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_refresh:
        raise HTTPException(status_code=401, detail={"code": "AUTH_SESSION_EXPIRED"})
    try:
        result = refresh(session, refresh_token=raw_refresh, csrf_token=csrf_token)
    except AuthError as exc:
        response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")
        raise _http_error(exc) from exc
    _set_refresh_cookie(response, result.refresh_token)
    return _token_response(result)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_auth_session),
) -> Response:
    try:
        logout(session, access_token=_bearer_value(credentials))
    except AuthError as exc:
        raise _http_error(exc) from exc
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/v1/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/auth/tenant-context", response_model=AuthTokenResponse)
def tenant_context_endpoint(
    payload: TenantContextRequest,
    request: Request,
    response: Response,
    csrf_token: str = Header(alias="X-CSRF-Token"),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_auth_session),
) -> AuthTokenResponse:
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_refresh:
        raise HTTPException(status_code=401, detail={"code": "AUTH_SESSION_EXPIRED"})
    try:
        result = switch_tenant(
            session,
            access_token=_bearer_value(credentials),
            refresh_token=raw_refresh,
            csrf_token=csrf_token,
            membership_id=payload.membership_id,
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    _set_refresh_cookie(response, result.refresh_token)
    return _token_response(result)


@router.get("/auth/memberships", response_model=list[MembershipSummary])
def memberships_endpoint(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_auth_session),
) -> list[MembershipSummary]:
    try:
        memberships = active_memberships_for_access_token(
            session,
            access_token=_bearer_value(credentials),
        )
    except AuthError as exc:
        raise _http_error(exc) from exc
    return [
        MembershipSummary(
            id=membership.id,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            tenant_slug=tenant.slug,
            status=membership.status,
        )
        for membership, tenant in memberships
    ]


@router.get("/me", response_model=MeResponse)
def me_endpoint(
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> MeResponse:
    try:
        return get_current_user(session, context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/me/permissions", response_model=PermissionResponse)
def permissions_endpoint(
    context: RequestContext = Depends(require_request_context),
) -> PermissionResponse:
    return PermissionResponse(
        membership_id=context.membership_id,
        permission_version=context.permission_version,
        permissions=sorted(context.permissions),
    )
