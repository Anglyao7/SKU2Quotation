from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt


ISSUER = "ai-trade-cloud"
AUDIENCE = "ai-trade-cloud-api"
ACCESS_TTL_SECONDS = int(os.getenv("AUTH_ACCESS_TTL_SECONDS", "600"))
SESSION_TTL_SECONDS = int(os.getenv("AUTH_SESSION_TTL_SECONDS", str(12 * 60 * 60)))
REFRESH_TTL_SECONDS = int(os.getenv("AUTH_REFRESH_TTL_SECONDS", str(30 * 24 * 60 * 60)))
REFRESH_COOKIE_NAME = "atc_refresh"
_EPHEMERAL_JWT_SECRET = secrets.token_urlsafe(48)
_EPHEMERAL_TOKEN_PEPPER = secrets.token_urlsafe(48)


class AccessTokenError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def _secret(name: str, fallback: str) -> str:
    value = os.getenv(name)
    app_env = os.getenv("APP_ENV", "development").lower()
    if value:
        if len(value) < 32:
            raise RuntimeError(f"{name} must be at least 32 characters")
        return value
    if app_env in {"production", "prod"}:
        raise RuntimeError(f"{name} is required in production")
    return fallback


def jwt_secret() -> str:
    return _secret("AUTH_JWT_SECRET", _EPHEMERAL_JWT_SECRET)


def token_pepper() -> str:
    return _secret("AUTH_TOKEN_PEPPER", _EPHEMERAL_TOKEN_PEPPER)


def hash_secret(value: str) -> str:
    return hmac.new(
        token_pepper().encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(
    *,
    user_id: UUID,
    session_id: UUID,
    session_version: int,
    membership_id: UUID | None,
    tenant_id: UUID | None,
    permission_version: int,
    locale: str,
) -> tuple[str, datetime]:
    issued_at = utcnow()
    expires_at = issued_at + timedelta(seconds=ACCESS_TTL_SECONDS)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "sid": str(session_id),
        "sv": session_version,
        "permission_version": permission_version,
        "jti": str(uuid4()),
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
        "locale": locale,
    }
    if membership_id is not None:
        claims["membership_id"] = str(membership_id)
    if tenant_id is not None:
        claims["tenant_id"] = str(tenant_id)
    return jwt.encode(claims, jwt_secret(), algorithm="HS256"), expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            jwt_secret(),
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "jti", "sid", "sub", "sv"]},
        )
    except jwt.PyJWTError as exc:
        raise AccessTokenError("invalid or expired access token") from exc
    return claims
