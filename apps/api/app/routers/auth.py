from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..auth_schemas import (
    AuthContext,
    AuthPublicConfig,
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
from ..services.auth.contracts import IdentityProviderError
from ..services.auth.oidc_provider import public_oidc_config
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..domain.errors import ApplicationError
from ..use_cases.authentication import get_current_user
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["authentication"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _http_error(exc: AuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers=NO_STORE_HEADERS,
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


@router.get("/auth/config", response_model=AuthPublicConfig)
def auth_config_endpoint(response: Response) -> AuthPublicConfig:
    """Return only browser-safe authorization metadata.

    Token, userinfo and JWKS endpoints as well as the client secret remain
    server-side. The browser needs only the authorization endpoint and public
    client metadata to start Authorization Code + PKCE.
    """

    response.headers.update(NO_STORE_HEADERS)
    profile = os.getenv("AUTH_PROFILE", "local_fake").lower()
    if profile == "local_fake" and os.getenv("APP_ENV", "development").lower() not in {
        "staging",
        "production",
        "prod",
    }:
        return AuthPublicConfig(provider="local_fake")
    if profile != "enterprise_oidc":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "AUTH_PROVIDER_UNAVAILABLE",
                "message": "approved identity provider is not configured",
            },
            headers=NO_STORE_HEADERS,
        )
    try:
        return AuthPublicConfig.model_validate(public_oidc_config())
    except IdentityProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "AUTH_PROVIDER_UNAVAILABLE",
                "message": "identity provider metadata is unavailable",
            },
            headers=NO_STORE_HEADERS,
        ) from exc


@router.post("/auth/login", response_model=AuthTokenResponse)
def login_endpoint(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_auth_session),
) -> AuthTokenResponse:
    response.headers.update(NO_STORE_HEADERS)
    enforce_rate_limit(
        request,
        scope="auth-login",
        limit=configured_limit("RATE_LIMIT_LOGIN_REQUESTS", 10),
        window_seconds=configured_limit(
            "RATE_LIMIT_LOGIN_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=payload.authorization_code,
    )
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
    response.headers.update(NO_STORE_HEADERS)
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    enforce_rate_limit(
        request,
        scope="auth-refresh",
        limit=configured_limit("RATE_LIMIT_REFRESH_REQUESTS", 30),
        window_seconds=configured_limit(
            "RATE_LIMIT_REFRESH_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=raw_refresh,
    )
    if not raw_refresh:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_SESSION_EXPIRED"},
            headers=NO_STORE_HEADERS,
        )
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
    response.headers.update(NO_STORE_HEADERS)
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
    response.headers.update(NO_STORE_HEADERS)
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_refresh:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_SESSION_EXPIRED"},
            headers=NO_STORE_HEADERS,
        )
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
