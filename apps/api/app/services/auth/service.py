from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...auth_schemas import LoginRequest
from ...identity_models import (
    AuthRefreshTokenRow,
    AuthSessionRow,
    MembershipRow,
    TenantRow,
    UserRow,
)
from .contracts import IdentityProviderError
from .fake_provider import FakeIdentityProviderAdapter
from .tokens import (
    ACCESS_TTL_SECONDS,
    REFRESH_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    AccessTokenError,
    create_access_token,
    decode_access_token,
    hash_secret,
    new_secret,
    utcnow,
)


class AuthError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class IssuedSession:
    auth_session: AuthSessionRow
    user: UserRow
    membership: MembershipRow | None
    tenant: TenantRow | None
    access_token: str
    refresh_token: str
    csrf_token: str
    requires_tenant_selection: bool


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _ip_hash(ip_address: str | None) -> str | None:
    if not ip_address:
        return None
    return hmac.new(
        hash_secret("ip-address").encode("ascii"),
        ip_address.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _active_memberships(session: Session, user_id: UUID) -> list[tuple[MembershipRow, TenantRow]]:
    return list(
        session.execute(
            select(MembershipRow, TenantRow)
            .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
            .where(
                MembershipRow.user_id == user_id,
                MembershipRow.status == "active",
                TenantRow.status == "active",
            )
            .order_by(MembershipRow.created_at, MembershipRow.id)
        ).all()
    )


def active_memberships_for_access_token(
    session: Session,
    *,
    access_token: str,
) -> list[tuple[MembershipRow, TenantRow]]:
    """Return only server-validated active memberships for the signed-in user."""
    _auth_session, user, _claims = session_from_access_token(
        session,
        access_token,
        context_required=False,
    )
    return _active_memberships(session, user.id)


def login(
    session: Session,
    request: LoginRequest,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> IssuedSession:
    if request.provider != "local_fake":
        raise AuthError(
            "AUTH_PROVIDER_UNAVAILABLE",
            "approved identity provider is not configured",
            status_code=503,
        )
    try:
        claim = FakeIdentityProviderAdapter().exchange_authorization_code(
            authorization_code=request.authorization_code,
            code_verifier=request.code_verifier,
            redirect_uri=request.redirect_uri,
        )
    except IdentityProviderError as exc:
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed") from exc

    user = session.scalar(
        select(UserRow).where(
            UserRow.identity_provider == claim.provider,
            UserRow.identity_subject == claim.subject,
        )
    )
    if user is None or user.status != "active":
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")

    memberships = _active_memberships(session, user.id)
    if not memberships:
        raise AuthError("AUTH_MEMBERSHIP_REQUIRED", "active membership is required", status_code=403)
    membership, tenant = memberships[0] if len(memberships) == 1 else (None, None)
    now = utcnow()
    refresh_token = new_secret()
    csrf_token = new_secret()
    auth_session = AuthSessionRow(
        id=uuid4(),
        user_id=user.id,
        active_membership_id=membership.id if membership else None,
        token_family_id=uuid4(),
        rotation_counter=0,
        session_version=1,
        permission_version=membership.permission_version if membership else 1,
        csrf_token_hash=hash_secret(csrf_token),
        device_label=request.device_label,
        user_agent_summary=(user_agent or "")[:300] or None,
        ip_hash=_ip_hash(ip_address),
        issued_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
        created_at=now,
        updated_at=now,
    )
    session.add(auth_session)
    session.flush()
    session.add(
        AuthRefreshTokenRow(
            id=uuid4(),
            auth_session_id=auth_session.id,
            token_hash=hash_secret(refresh_token),
            sequence_number=0,
            issued_at=now,
            expires_at=now + timedelta(seconds=REFRESH_TTL_SECONDS),
            created_at=now,
        )
    )
    user.last_login_at = now
    access_token, _ = create_access_token(
        user_id=user.id,
        session_id=auth_session.id,
        session_version=auth_session.session_version,
        membership_id=membership.id if membership else None,
        tenant_id=tenant.id if tenant else None,
        permission_version=auth_session.permission_version,
        locale=user.locale,
    )
    session.commit()
    return IssuedSession(
        auth_session=auth_session,
        user=user,
        membership=membership,
        tenant=tenant,
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
        requires_tenant_selection=len(memberships) > 1,
    )


def _load_valid_context(
    session: Session,
    auth_session: AuthSessionRow,
) -> tuple[UserRow, MembershipRow | None, TenantRow | None]:
    now = utcnow()
    if auth_session.revoked_at is not None or _aware(auth_session.expires_at) <= now:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    user = session.get(UserRow, auth_session.user_id)
    if user is None or user.status != "active":
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    if auth_session.active_membership_id is None:
        return user, None, None
    pair = session.execute(
        select(MembershipRow, TenantRow)
        .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
        .where(
            MembershipRow.id == auth_session.active_membership_id,
            MembershipRow.user_id == user.id,
            MembershipRow.status == "active",
            TenantRow.status == "active",
        )
    ).one_or_none()
    if pair is None:
        raise AuthError("TENANT_CONTEXT_INVALID", "active membership is required", status_code=403)
    membership, tenant = pair
    return user, membership, tenant


def _revoke_family(session: Session, auth_session: AuthSessionRow, reason: str) -> None:
    now = utcnow()
    auth_session.revoked_at = auth_session.revoked_at or now
    auth_session.revocation_reason = auth_session.revocation_reason or reason
    auth_session.session_version += 1
    auth_session.updated_at = now
    tokens = session.scalars(
        select(AuthRefreshTokenRow).where(
            AuthRefreshTokenRow.auth_session_id == auth_session.id,
            AuthRefreshTokenRow.revoked_at.is_(None),
        )
    ).all()
    for token in tokens:
        token.revoked_at = now
        token.revocation_reason = reason


def _rotate(
    session: Session,
    *,
    refresh_token: str,
    csrf_token: str,
) -> IssuedSession:
    token_hash = hash_secret(refresh_token)
    token = session.scalar(
        select(AuthRefreshTokenRow)
        .where(AuthRefreshTokenRow.token_hash == token_hash)
        .with_for_update()
    )
    if token is None:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    auth_session = session.scalar(
        select(AuthSessionRow)
        .where(AuthSessionRow.id == token.auth_session_id)
        .with_for_update()
    )
    if auth_session is None:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    if token.used_at is not None or token.revoked_at is not None:
        _revoke_family(session, auth_session, "REFRESH_REUSE")
        session.commit()
        raise AuthError("AUTH_REFRESH_REUSE_DETECTED", "refresh token reuse detected")
    now = utcnow()
    if _aware(token.expires_at) <= now:
        _revoke_family(session, auth_session, "REFRESH_EXPIRED")
        session.commit()
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    if not hmac.compare_digest(auth_session.csrf_token_hash, hash_secret(csrf_token)):
        raise AuthError("AUTH_CSRF_INVALID", "CSRF validation failed", status_code=403)

    user, membership, tenant = _load_valid_context(session, auth_session)
    new_refresh = new_secret()
    new_csrf = new_secret()
    next_token = AuthRefreshTokenRow(
        id=uuid4(),
        auth_session_id=auth_session.id,
        token_hash=hash_secret(new_refresh),
        sequence_number=token.sequence_number + 1,
        issued_at=now,
        expires_at=now + timedelta(seconds=REFRESH_TTL_SECONDS),
        created_at=now,
    )
    session.add(next_token)
    session.flush()
    token.used_at = now
    token.replaced_by_token_id = next_token.id
    auth_session.rotation_counter += 1
    auth_session.last_seen_at = now
    auth_session.updated_at = now
    auth_session.permission_version = membership.permission_version if membership else 1
    auth_session.csrf_token_hash = hash_secret(new_csrf)
    access_token, _ = create_access_token(
        user_id=user.id,
        session_id=auth_session.id,
        session_version=auth_session.session_version,
        membership_id=membership.id if membership else None,
        tenant_id=tenant.id if tenant else None,
        permission_version=auth_session.permission_version,
        locale=user.locale,
    )
    session.commit()
    return IssuedSession(
        auth_session=auth_session,
        user=user,
        membership=membership,
        tenant=tenant,
        access_token=access_token,
        refresh_token=new_refresh,
        csrf_token=new_csrf,
        requires_tenant_selection=membership is None,
    )


def refresh(session: Session, *, refresh_token: str, csrf_token: str) -> IssuedSession:
    return _rotate(session, refresh_token=refresh_token, csrf_token=csrf_token)


def switch_tenant(
    session: Session,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
    membership_id: UUID,
) -> IssuedSession:
    auth_session, user, _claims = session_from_access_token(session, access_token, context_required=False)
    target = session.execute(
        select(MembershipRow, TenantRow)
        .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
        .where(
            MembershipRow.id == membership_id,
            MembershipRow.user_id == user.id,
            MembershipRow.status == "active",
            TenantRow.status == "active",
        )
    ).one_or_none()
    if target is None:
        raise AuthError("TENANT_CONTEXT_INVALID", "target membership is not active", status_code=403)
    membership, _tenant = target
    auth_session.active_membership_id = membership.id
    auth_session.permission_version = membership.permission_version
    auth_session.session_version += 1
    session.flush()
    return _rotate(session, refresh_token=refresh_token, csrf_token=csrf_token)


def logout(session: Session, *, access_token: str) -> None:
    try:
        claims = decode_access_token(access_token)
        session_id = UUID(str(claims["sid"]))
    except (AccessTokenError, KeyError, ValueError) as exc:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked") from exc
    auth_session = session.get(AuthSessionRow, session_id)
    if auth_session is None:
        return
    if auth_session.revoked_at is None:
        _revoke_family(session, auth_session, "LOGOUT")
        session.commit()


def session_from_access_token(
    session: Session,
    access_token: str,
    *,
    context_required: bool = True,
) -> tuple[AuthSessionRow, UserRow, dict[str, Any]]:
    try:
        claims = decode_access_token(access_token)
        session_id = UUID(str(claims["sid"]))
        user_id = UUID(str(claims["sub"]))
    except (AccessTokenError, KeyError, ValueError) as exc:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked") from exc
    auth_session = session.get(AuthSessionRow, session_id)
    if auth_session is None or auth_session.user_id != user_id:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    user, membership, tenant = _load_valid_context(session, auth_session)
    if int(claims.get("sv", -1)) != auth_session.session_version:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    if context_required:
        if membership is None or tenant is None:
            raise AuthError("TENANT_CONTEXT_REQUIRED", "tenant selection is required", status_code=403)
        if claims.get("membership_id") != str(membership.id) or claims.get("tenant_id") != str(tenant.id):
            raise AuthError("AUTH_SESSION_EXPIRED", "session context is stale")
        if int(claims.get("permission_version", -1)) != membership.permission_version:
            raise AuthError("AUTH_PERMISSION_STALE", "permission context is stale")
    return auth_session, user, claims


def access_ttl_seconds() -> int:
    return ACCESS_TTL_SECONDS
