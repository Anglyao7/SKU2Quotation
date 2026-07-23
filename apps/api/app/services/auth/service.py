from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...auth_schemas import LoginRequest, PasswordLoginRequest
from ...identity_models import (
    AuthRefreshTokenRow,
    AuthSessionRow,
    MembershipRow,
    TenantRow,
    UserRow,
)
from ..invitation_email_lock import acquire_invitation_email_lock
from .contracts import IdentityClaim, IdentityProviderError, IdentityProviderPort
from .fake_provider import FakeIdentityProviderAdapter
from .oidc_provider import OidcIdentityProviderAdapter
from .tokens import (
    ACCESS_TTL_SECONDS,
    REFRESH_TTL_SECONDS,
    SESSION_TTL_SECONDS,
    AccessTokenError,
    create_access_token,
    decode_access_token,
    derive_rotation_secret,
    hash_secret,
    new_secret,
    refresh_retry_grace_seconds,
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


def _identity_adapter(provider: str) -> IdentityProviderPort:
    configured = os.getenv("AUTH_PROFILE", "local_fake").lower()
    app_env = os.getenv("APP_ENV", "development").lower()
    if (
        provider == "local_fake"
        and configured == "local_fake"
        and app_env not in {"staging", "production", "prod"}
    ):
        return FakeIdentityProviderAdapter()
    if provider == "enterprise_oidc" and configured == "enterprise_oidc":
        return OidcIdentityProviderAdapter()
    raise AuthError(
        "AUTH_PROVIDER_UNAVAILABLE",
        "approved identity provider is not configured",
        status_code=503,
    )


def _activate_verified_invitation(
    session: Session,
    *,
    claim: IdentityClaim,
) -> UserRow:
    if (
        not claim.email_verified
        or not claim.email_normalized
        or not claim.provider.startswith("oidc:")
    ):
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")
    normalized_email = claim.email_normalized.strip().lower()
    acquire_invitation_email_lock(
        session,
        normalized_email=normalized_email,
    )
    candidates = session.scalars(
        select(UserRow).where(
            UserRow.identity_provider == "pending_oidc",
            UserRow.email_normalized == normalized_email,
            UserRow.status == "invited",
        )
    ).all()
    if len(candidates) != 1:
        # No just-in-time account creation and no ambiguous cross-tenant email
        # binding. An operator must create exactly one pending identity first.
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")
    user = candidates[0]
    invited_pairs = session.execute(
        select(MembershipRow, TenantRow)
        .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
        .where(
            MembershipRow.user_id == user.id,
            MembershipRow.status == "invited",
            TenantRow.status == "active",
        )
    ).all()
    if not invited_pairs:
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")
    now = utcnow()
    try:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            bound = session.execute(
                text(
                    "SELECT public.atc_bind_oidc_invitation("
                    ":user_id, :email, :provider, :subject, :display_name, :tenant_ids)"
                ),
                {
                    "user_id": user.id,
                    "email": normalized_email,
                    "provider": claim.provider,
                    "subject": claim.subject,
                    "display_name": claim.display_name or user.display_name,
                    "tenant_ids": [tenant.id for _membership, tenant in invited_pairs],
                },
            ).scalar_one()
            if bound is not True:
                raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")
            session.expire(user)
        else:
            user.identity_provider = claim.provider
            user.identity_subject = claim.subject
            user.status = "active"
            if claim.display_name:
                user.display_name = claim.display_name[:120]
            for membership, _tenant in invited_pairs:
                membership.status = "active"
                membership.joined_at = membership.joined_at or now
        session.flush()
    except (SQLAlchemyError, AuthError) as exc:
        session.rollback()
        if isinstance(exc, AuthError):
            raise
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed") from exc
    return user


def login(
    session: Session,
    request: LoginRequest,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> IssuedSession:
    adapter = _identity_adapter(request.provider)
    try:
        claim = adapter.exchange_authorization_code(
            authorization_code=request.authorization_code,
            code_verifier=request.code_verifier,
            redirect_uri=request.redirect_uri,
            nonce=request.nonce,
        )
    except IdentityProviderError as exc:
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed") from exc

    return _issue_authenticated_session(
        session,
        claim=claim,
        provider=request.provider,
        device_label=request.device_label,
        user_agent=user_agent,
        ip_address=ip_address,
    )


def password_login(
    session: Session,
    request: PasswordLoginRequest,
    *,
    user_agent: str | None,
    ip_address: str | None,
) -> IssuedSession:
    adapter = _identity_adapter("enterprise_oidc")
    password = request.password.get_secret_value()
    if not password or len(password) > 1024:
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")
    try:
        claim = adapter.authenticate_password(
            identifier=request.identifier,
            password=password,
        )
    except IdentityProviderError as exc:
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed") from exc
    return _issue_authenticated_session(
        session,
        claim=claim,
        provider="enterprise_oidc",
        device_label=request.device_label,
        user_agent=user_agent,
        ip_address=ip_address,
    )


def _issue_authenticated_session(
    session: Session,
    *,
    claim: IdentityClaim,
    provider: str,
    device_label: str | None,
    user_agent: str | None,
    ip_address: str | None,
) -> IssuedSession:
    if provider == "enterprise_oidc" and (
        not claim.email_verified or not claim.email_normalized
    ):
        raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")

    user = session.scalar(
        select(UserRow).where(
            UserRow.identity_provider == claim.provider,
            UserRow.identity_subject == claim.subject,
        )
    )
    if user is None and provider == "enterprise_oidc":
        user = _activate_verified_invitation(session, claim=claim)
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
        device_label=device_label,
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
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        touched = session.execute(
            text(
                "SELECT public.atc_touch_user_login("
                ":user_id, :provider, :subject)"
            ),
            {
                "user_id": user.id,
                "provider": claim.provider,
                "subject": claim.subject,
            },
        ).scalar_one()
        if touched is not True:
            session.rollback()
            raise AuthError("AUTH_INVALID_CREDENTIALS", "authentication failed")
    else:
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


def _switch_request_identity(
    switch_claims: dict[str, Any] | None,
) -> tuple[UUID, UUID, int] | None:
    if switch_claims is None:
        return None
    try:
        return (
            UUID(str(switch_claims["sid"])),
            UUID(str(switch_claims["sub"])),
            int(switch_claims["sv"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked") from exc


def _rotation_request_hash(
    *,
    csrf_token: str,
    target_membership_id: UUID | None,
    switch_identity: tuple[UUID, UUID, int] | None,
) -> str:
    if (target_membership_id is None) != (switch_identity is None):
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    operation = (
        "refresh"
        if target_membership_id is None
        else f"tenant-context:{target_membership_id}:{switch_identity[2]}"
    )
    return hash_secret(f"refresh-retry-binding:v1:{operation}:{csrf_token}")


def _retry_recent_rotation(
    session: Session,
    *,
    token: AuthRefreshTokenRow,
    auth_session: AuthSessionRow,
    refresh_token: str,
    request_hash: str,
    now: datetime,
) -> IssuedSession | None:
    """Return the already-issued successor for one bounded concurrent retry.

    The successor secrets are recomputed from the predecessor and the
    server-side pepper. Only hashes and the short grace deadline are persisted.
    """

    if (
        token.used_at is None
        or token.revoked_at is not None
        or token.replaced_by_token_id is None
        or token.rotation_request_hash is None
        or token.retry_grace_expires_at is None
        or _aware(token.retry_grace_expires_at) < now
        or _aware(token.expires_at) <= now
        or auth_session.revoked_at is not None
        or _aware(auth_session.expires_at) <= now
        or not hmac.compare_digest(token.rotation_request_hash, request_hash)
    ):
        return None
    successor = session.get(AuthRefreshTokenRow, token.replaced_by_token_id)
    if (
        successor is None
        or successor.auth_session_id != auth_session.id
        or successor.sequence_number != token.sequence_number + 1
        or successor.sequence_number != auth_session.rotation_counter
        or successor.used_at is not None
        or successor.revoked_at is not None
        or _aware(successor.expires_at) <= now
    ):
        return None

    successor_refresh = derive_rotation_secret(
        refresh_token=refresh_token,
        token_id=token.id,
        purpose="refresh",
    )
    successor_csrf = derive_rotation_secret(
        refresh_token=refresh_token,
        token_id=token.id,
        purpose="csrf",
    )
    if (
        not hmac.compare_digest(successor.token_hash, hash_secret(successor_refresh))
        or not hmac.compare_digest(
            auth_session.csrf_token_hash,
            hash_secret(successor_csrf),
        )
    ):
        return None

    user, membership, tenant = _load_valid_context(session, auth_session)
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
        refresh_token=successor_refresh,
        csrf_token=successor_csrf,
        requires_tenant_selection=membership is None,
    )


def _rotate(
    session: Session,
    *,
    refresh_token: str,
    csrf_token: str,
    target_membership_id: UUID | None = None,
    switch_claims: dict[str, Any] | None = None,
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
    switch_identity = _switch_request_identity(switch_claims)
    if switch_identity is not None:
        expected_session_id, expected_user_id, expected_session_version = switch_identity
        if (
            expected_session_id != auth_session.id
            or expected_user_id != auth_session.user_id
        ):
            raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    request_hash = _rotation_request_hash(
        csrf_token=csrf_token,
        target_membership_id=target_membership_id,
        switch_identity=switch_identity,
    )
    now = utcnow()
    if token.used_at is not None or token.revoked_at is not None:
        retried = _retry_recent_rotation(
            session,
            token=token,
            auth_session=auth_session,
            refresh_token=refresh_token,
            request_hash=request_hash,
            now=now,
        )
        if retried is not None:
            return retried
        _revoke_family(session, auth_session, "REFRESH_REUSE")
        session.commit()
        raise AuthError("AUTH_REFRESH_REUSE_DETECTED", "refresh token reuse detected")
    if (
        switch_identity is not None
        and expected_session_version != auth_session.session_version
    ):
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    if _aware(token.expires_at) <= now:
        _revoke_family(session, auth_session, "REFRESH_EXPIRED")
        session.commit()
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked")
    if not hmac.compare_digest(auth_session.csrf_token_hash, hash_secret(csrf_token)):
        raise AuthError("AUTH_CSRF_INVALID", "CSRF validation failed", status_code=403)

    if target_membership_id is not None:
        target = session.execute(
            select(MembershipRow, TenantRow)
            .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
            .where(
                MembershipRow.id == target_membership_id,
                MembershipRow.user_id == auth_session.user_id,
                MembershipRow.status == "active",
                TenantRow.status == "active",
            )
        ).one_or_none()
        if target is None:
            raise AuthError(
                "TENANT_CONTEXT_INVALID",
                "target membership is not active",
                status_code=403,
            )
        target_membership, _target_tenant = target
        auth_session.active_membership_id = target_membership.id
        auth_session.permission_version = target_membership.permission_version
        auth_session.session_version += 1

    user, membership, tenant = _load_valid_context(session, auth_session)
    new_refresh = derive_rotation_secret(
        refresh_token=refresh_token,
        token_id=token.id,
        purpose="refresh",
    )
    new_csrf = derive_rotation_secret(
        refresh_token=refresh_token,
        token_id=token.id,
        purpose="csrf",
    )
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
    token.rotation_request_hash = request_hash
    token.retry_grace_expires_at = now + timedelta(
        seconds=refresh_retry_grace_seconds()
    )
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
    try:
        claims = decode_access_token(access_token)
    except AccessTokenError as exc:
        raise AuthError("AUTH_SESSION_EXPIRED", "session is expired or revoked") from exc
    return _rotate(
        session,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
        target_membership_id=membership_id,
        switch_claims=claims,
    )


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
