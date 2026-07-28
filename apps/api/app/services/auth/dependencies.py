from __future__ import annotations

import os
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...constants import (
    DEFAULT_MEMBERSHIP_ID,
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
)
from ...database import get_auth_session, get_session, set_request_context
from ...identity_models import MembershipRow, TenantRow, UserRow
from ..rbac import list_permissions
from .service import AuthError, session_from_access_token
from .tokens import AccessTokenError, decode_access_token


bearer = HTTPBearer(auto_error=False)
_permission_cache_lock = Lock()


@dataclass(frozen=True)
class _PermissionCacheEntry:
    expires_at: float
    permissions: frozenset[str]


_permission_cache: dict[tuple[UUID, UUID, int], _PermissionCacheEntry] = {}


@dataclass(frozen=True)
class RequestContext:
    user_id: UUID
    membership_id: UUID
    tenant_id: UUID
    organization_id: UUID
    locale: str
    permission_version: int
    permissions: frozenset[str]
    is_platform_admin: bool
    account_scope: str = "STAFF"


def _permission_cache_ttl_seconds() -> float:
    if os.getenv("APP_ENV", "development").lower() == "test":
        return 0.0
    raw_value = os.getenv("AUTH_PERMISSION_CACHE_TTL_SECONDS", "15")
    try:
        return max(0.0, min(float(raw_value), 300.0))
    except ValueError:
        return 15.0


def _permissions_for_context(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permission_version: int,
) -> frozenset[str]:
    ttl_seconds = _permission_cache_ttl_seconds()
    if ttl_seconds <= 0:
        return frozenset(
            list_permissions(session, tenant_id=tenant_id, user_id=user_id)
        )
    key = (tenant_id, user_id, permission_version)
    now = monotonic()
    with _permission_cache_lock:
        cached = _permission_cache.get(key)
        if cached is not None and cached.expires_at > now:
            return cached.permissions
        if len(_permission_cache) >= 2048:
            expired = [
                cache_key
                for cache_key, entry in _permission_cache.items()
                if entry.expires_at <= now
            ]
            for cache_key in expired:
                _permission_cache.pop(cache_key, None)
            if len(_permission_cache) >= 2048:
                _permission_cache.clear()
    permissions = frozenset(
        list_permissions(session, tenant_id=tenant_id, user_id=user_id)
    )
    with _permission_cache_lock:
        _permission_cache[key] = _PermissionCacheEntry(
            expires_at=now + ttl_seconds,
            permissions=permissions,
        )
    return permissions


def _test_bypass(session: Session) -> RequestContext | None:
    enabled = os.getenv("AUTH_TEST_BYPASS", "false").lower() in {"1", "true", "yes"}
    app_env = os.getenv("APP_ENV", "development").lower()
    if not enabled:
        return None
    if app_env != "test":
        raise RuntimeError("AUTH_TEST_BYPASS is only allowed when APP_ENV=test")
    set_request_context(
        session,
        organization_id=DEFAULT_ORGANIZATION_ID,
        tenant_id=DEFAULT_TENANT_ID,
        user_id=DEFAULT_OWNER_USER_ID,
    )
    permissions = frozenset(
        list_permissions(
            session,
            tenant_id=DEFAULT_TENANT_ID,
            user_id=DEFAULT_OWNER_USER_ID,
        )
    )
    context = RequestContext(
        user_id=DEFAULT_OWNER_USER_ID,
        membership_id=DEFAULT_MEMBERSHIP_ID,
        tenant_id=DEFAULT_TENANT_ID,
        organization_id=DEFAULT_ORGANIZATION_ID,
        locale="zh-CN",
        permission_version=1,
        permissions=permissions,
        is_platform_admin=True,
        account_scope="STAFF",
    )
    session.info["request_context"] = context
    return context


def require_request_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
    auth_session: Session = Depends(get_auth_session),
) -> RequestContext:
    bypass = _test_bypass(session)
    if bypass is not None:
        return bypass
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_REQUIRED", "message": "authentication is required"},
        )
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = UUID(str(claims["sub"]))
    except (AccessTokenError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_SESSION_EXPIRED", "message": "session is expired or revoked"},
        ) from exc

    # The identity repository uses a narrowly privileged connection in
    # production. Signed claims never authorize business data by themselves:
    # the server-side Session, Membership and Tenant are reloaded first.
    try:
        auth_session, user, _ = session_from_access_token(
            auth_session,
            credentials.credentials,
            context_required=True,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    trusted_membership = auth_session.active_membership
    trusted_tenant = trusted_membership.tenant if trusted_membership is not None else None
    if trusted_membership is None or trusted_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_CONTEXT_INVALID", "message": "active membership is required"},
        )
    membership_id = trusted_membership.id
    tenant_id = trusted_tenant.id
    set_request_context(
        session,
        organization_id=trusted_tenant.organization_id,
        tenant_id=trusted_tenant.id,
        user_id=user.id,
    )
    pair = session.execute(
        select(MembershipRow, TenantRow)
        .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
        .where(
            MembershipRow.id == membership_id,
            MembershipRow.user_id == user_id,
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.status == "active",
            TenantRow.status == "active",
        )
    ).one_or_none()
    if pair is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_CONTEXT_INVALID", "message": "active membership is required"},
        )
    membership, tenant = pair
    if auth_session.active_membership_id != membership.id or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_SESSION_EXPIRED", "message": "session is expired or revoked"},
        )
    permissions = _permissions_for_context(
        session,
        tenant_id=tenant.id,
        user_id=user.id,
        permission_version=membership.permission_version,
    )
    context = RequestContext(
        user_id=user.id,
        membership_id=membership.id,
        tenant_id=tenant.id,
        organization_id=tenant.organization_id,
        locale=user.locale,
        permission_version=membership.permission_version,
        permissions=permissions,
        is_platform_admin=bool(user.is_platform_admin),
        account_scope=membership.account_scope,
    )
    session.info["request_context"] = context
    return context


def get_authenticated_session(
    _context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> Session:
    return session


def current_context(session: Session) -> RequestContext:
    context = session.info.get("request_context")
    if not isinstance(context, RequestContext):
        raise RuntimeError("trusted request context is not bound to this session")
    return context
