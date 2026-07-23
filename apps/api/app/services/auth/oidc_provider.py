from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt

from .contracts import IdentityClaim, IdentityProviderError


SAFE_SIGNING_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"}
)


@dataclass(frozen=True, slots=True)
class OidcSettings:
    issuer: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...]
    redirect_uris: tuple[str, ...]
    token_endpoint_auth_method: str
    allowed_algorithms: tuple[str, ...]
    allowed_endpoint_hosts: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class OidcDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    end_session_endpoint: str | None
    signing_algorithms: tuple[str, ...]


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _space_separated(value: str) -> tuple[str, ...]:
    return tuple(item for item in value.split() if item)


def load_oidc_settings() -> OidcSettings:
    try:
        timeout = float(os.getenv("OIDC_HTTP_TIMEOUT_SECONDS", "10"))
    except ValueError as exc:
        raise IdentityProviderError("OIDC timeout is invalid") from exc
    issuer = os.getenv("OIDC_ISSUER", "").strip()
    issuer_host = (urlsplit(issuer).hostname or "").lower()
    allowed_endpoint_hosts = _csv(os.getenv("OIDC_ALLOWED_ENDPOINT_HOSTS", ""))
    settings = OidcSettings(
        issuer=issuer,
        client_id=os.getenv("OIDC_CLIENT_ID", "").strip(),
        client_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
        scopes=_space_separated(
            os.getenv("OIDC_SCOPES", "openid profile email")
        ),
        redirect_uris=_csv(os.getenv("OIDC_REDIRECT_URIS", "")),
        token_endpoint_auth_method=os.getenv(
            "OIDC_TOKEN_ENDPOINT_AUTH_METHOD", "client_secret_basic"
        ).strip(),
        allowed_algorithms=_csv(
            os.getenv("OIDC_ALLOWED_ALGORITHMS", "RS256,ES256")
        ),
        allowed_endpoint_hosts=tuple(
            host.lower() for host in (allowed_endpoint_hosts or (issuer_host,))
        ),
        timeout_seconds=timeout,
    )
    if (
        not settings.issuer
        or not settings.client_id
        or not settings.redirect_uris
        or "openid" not in settings.scopes
        or not settings.allowed_algorithms
        or not set(settings.allowed_algorithms) <= SAFE_SIGNING_ALGORITHMS
        or not settings.allowed_endpoint_hosts
        or settings.timeout_seconds <= 0
        or settings.timeout_seconds > 30
    ):
        raise IdentityProviderError("OIDC configuration is invalid")
    if settings.token_endpoint_auth_method not in {
        "client_secret_basic",
        "client_secret_post",
        "none",
    }:
        raise IdentityProviderError("OIDC client authentication method is invalid")
    if (
        settings.token_endpoint_auth_method != "none"
        and not settings.client_secret
    ):
        raise IdentityProviderError("OIDC client secret is missing")
    return settings


def _is_forbidden_ip_literal(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _https_endpoint(
    value: object,
    *,
    issuer: str,
    allowed_hosts: tuple[str, ...],
    required: bool = True,
) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise IdentityProviderError("OIDC discovery document is invalid")
    parsed = urlsplit(value)
    issuer_parsed = urlsplit(issuer)
    try:
        parsed_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        issuer_port = issuer_parsed.port or (
            443 if issuer_parsed.scheme == "https" else 80
        )
    except ValueError as exc:
        raise IdentityProviderError("OIDC discovery endpoint is not trusted") from exc
    app_env = os.getenv("APP_ENV", "development").lower()
    local_development = (
        app_env not in {"staging", "production", "prod"}
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    )
    if (
        (parsed.scheme != "https" and not local_development)
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.hostname
        or parsed.hostname.lower() not in allowed_hosts
        or (
            parsed.hostname.lower() == (issuer_parsed.hostname or "").lower()
            and (parsed.scheme, parsed_port) != (issuer_parsed.scheme, issuer_port)
        )
        or (
            app_env in {"staging", "production", "prod"}
            and (
                parsed.hostname.lower() in {"localhost", "localhost.localdomain"}
                or parsed.hostname.lower().endswith(".localhost")
                or _is_forbidden_ip_literal(parsed.hostname)
            )
        )
    ):
        raise IdentityProviderError("OIDC discovery endpoint is not trusted")
    return value


@lru_cache(maxsize=8)
def get_oidc_discovery(
    issuer: str,
    timeout_seconds: float,
    allowed_hosts: tuple[str, ...],
) -> OidcDiscovery:
    discovery_url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    _https_endpoint(
        discovery_url,
        issuer=issuer,
        allowed_hosts=allowed_hosts,
    )
    try:
        response = httpx.get(
            discovery_url,
            headers={"Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise IdentityProviderError("OIDC discovery failed") from exc
    if not isinstance(payload, dict) or payload.get("issuer") != issuer:
        raise IdentityProviderError("OIDC issuer mismatch")
    advertised_algorithms = payload.get("id_token_signing_alg_values_supported", ())
    if not isinstance(advertised_algorithms, list):
        advertised_algorithms = ()
    return OidcDiscovery(
        issuer=issuer,
        authorization_endpoint=str(
            _https_endpoint(
                payload.get("authorization_endpoint"),
                issuer=issuer,
                allowed_hosts=allowed_hosts,
            )
        ),
        token_endpoint=str(
            _https_endpoint(
                payload.get("token_endpoint"),
                issuer=issuer,
                allowed_hosts=allowed_hosts,
            )
        ),
        jwks_uri=str(
            _https_endpoint(
                payload.get("jwks_uri"),
                issuer=issuer,
                allowed_hosts=allowed_hosts,
            )
        ),
        userinfo_endpoint=_https_endpoint(
            payload.get("userinfo_endpoint"),
            issuer=issuer,
            allowed_hosts=allowed_hosts,
            required=False,
        ),
        end_session_endpoint=_https_endpoint(
            payload.get("end_session_endpoint"),
            issuer=issuer,
            allowed_hosts=allowed_hosts,
            required=False,
        ),
        signing_algorithms=tuple(
            item for item in advertised_algorithms if isinstance(item, str)
        ),
    )


def oidc_provider_key(issuer: str) -> str:
    digest = hashlib.sha256(issuer.encode("utf-8")).hexdigest()[:32]
    return f"oidc:{digest}"


_JWKS_CACHE: dict[str, tuple[float, tuple[dict[str, Any], ...]]] = {}
_JWKS_LOCK = threading.Lock()
_JWKS_TTL_SECONDS = 300
_JWKS_MAX_DOCUMENT_BYTES = 1_000_000


def _load_jwks(
    jwks_uri: str,
    timeout_seconds: float,
    *,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], ...]:
    now = time.monotonic()
    with _JWKS_LOCK:
        cached = _JWKS_CACHE.get(jwks_uri)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < _JWKS_TTL_SECONDS
        ):
            return cached[1]
    try:
        response = httpx.get(
            jwks_uri,
            headers={"Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > _JWKS_MAX_DOCUMENT_BYTES:
            raise IdentityProviderError("OIDC JWKS document is too large")
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise IdentityProviderError("OIDC JWKS retrieval failed") from exc
    keys = payload.get("keys") if isinstance(payload, dict) else None
    if not isinstance(keys, list) or not keys or len(keys) > 100:
        raise IdentityProviderError("OIDC JWKS document is invalid")
    normalized = tuple(item for item in keys if isinstance(item, dict))
    if not normalized:
        raise IdentityProviderError("OIDC JWKS document is invalid")
    with _JWKS_LOCK:
        if len(_JWKS_CACHE) >= 8 and jwks_uri not in _JWKS_CACHE:
            oldest = min(_JWKS_CACHE, key=lambda uri: _JWKS_CACHE[uri][0])
            _JWKS_CACHE.pop(oldest, None)
        _JWKS_CACHE[jwks_uri] = (now, normalized)
    return normalized


def get_signing_key(
    id_token: str,
    *,
    jwks_uri: str,
    algorithm: str,
    timeout_seconds: float,
) -> object:
    header = jwt.get_unverified_header(id_token)
    key_id = header.get("kid")
    if not isinstance(key_id, str) or not key_id:
        raise IdentityProviderError("OIDC ID token key identifier is missing")
    for refresh in (False, True):
        candidates = [
            item
            for item in _load_jwks(
                jwks_uri,
                timeout_seconds,
                force_refresh=refresh,
            )
            if item.get("kid") == key_id
            and (item.get("alg") is None or item.get("alg") == algorithm)
        ]
        if len(candidates) == 1:
            try:
                return jwt.PyJWK.from_dict(
                    candidates[0],
                    algorithm=algorithm,
                ).key
            except (jwt.PyJWTError, ValueError) as exc:
                raise IdentityProviderError("OIDC signing key is invalid") from exc
        if len(candidates) > 1:
            raise IdentityProviderError("OIDC signing key is ambiguous")
    raise IdentityProviderError("OIDC signing key was not found")


def public_oidc_config() -> dict[str, object]:
    settings = load_oidc_settings()
    discovery = get_oidc_discovery(
        settings.issuer,
        settings.timeout_seconds,
        settings.allowed_endpoint_hosts,
    )
    if discovery.end_session_endpoint is None:
        raise IdentityProviderError("OIDC end-session endpoint is missing")
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    post_logout_redirect_uri = os.getenv(
        "OIDC_POST_LOGOUT_REDIRECT_URI",
        public_base_url + "/login",
    ).strip()
    parsed_logout = urlsplit(post_logout_redirect_uri)
    app_env = os.getenv("APP_ENV", "development").lower()
    if (
        not parsed_logout.netloc
        or parsed_logout.query
        or parsed_logout.fragment
        or not public_base_url
        or post_logout_redirect_uri != f"{public_base_url}/login"
        or (
            app_env in {"staging", "production", "prod"}
            and parsed_logout.scheme != "https"
        )
    ):
        raise IdentityProviderError("OIDC post-logout redirect URI is invalid")
    return {
        "provider": "enterprise_oidc",
        "client_id": settings.client_id,
        "authorization_endpoint": discovery.authorization_endpoint,
        "end_session_endpoint": discovery.end_session_endpoint,
        "post_logout_redirect_uri": post_logout_redirect_uri,
        "scopes": list(settings.scopes),
        "code_challenge_method": "S256",
    }


class OidcIdentityProviderAdapter:
    provider_name = "enterprise_oidc"

    def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
        code_verifier: str,
        redirect_uri: str,
        nonce: str | None = None,
    ) -> IdentityClaim:
        settings = load_oidc_settings()
        if redirect_uri not in settings.redirect_uris:
            raise IdentityProviderError("OIDC redirect URI is not allowed")
        if not nonce or len(nonce) < 32:
            raise IdentityProviderError("OIDC nonce is missing")
        discovery = get_oidc_discovery(
            settings.issuer,
            settings.timeout_seconds,
            settings.allowed_endpoint_hosts,
        )
        token_payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "client_id": settings.client_id,
        }
        request_auth: tuple[str, str] | None = None
        if settings.token_endpoint_auth_method == "client_secret_basic":
            request_auth = (settings.client_id, settings.client_secret)
        elif settings.token_endpoint_auth_method == "client_secret_post":
            token_payload["client_secret"] = settings.client_secret
        try:
            token_response = httpx.post(
                discovery.token_endpoint,
                data=token_payload,
                auth=request_auth,
                headers={"Accept": "application/json"},
                timeout=settings.timeout_seconds,
                follow_redirects=False,
            )
            token_response.raise_for_status()
            tokens = token_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityProviderError("OIDC token exchange failed") from exc
        if not isinstance(tokens, dict):
            raise IdentityProviderError("OIDC token response is invalid")
        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token")
        token_type = tokens.get("token_type", "Bearer")
        if (
            not isinstance(id_token, str)
            or not isinstance(access_token, str)
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
        ):
            raise IdentityProviderError("OIDC token response is incomplete")

        claims = self._verify_id_token(
            id_token=id_token,
            nonce=nonce,
            settings=settings,
            discovery=discovery,
        )
        userinfo = self._userinfo(
            endpoint=discovery.userinfo_endpoint,
            access_token=access_token,
            timeout=settings.timeout_seconds,
        )
        if userinfo and userinfo.get("sub") != claims.get("sub"):
            raise IdentityProviderError("OIDC userinfo subject mismatch")
        effective = {**claims, **(userinfo or {})}
        email = effective.get("email")
        email_verified = effective.get("email_verified") is True
        if not isinstance(email, str) or not email_verified:
            raise IdentityProviderError("OIDC verified email is required")
        normalized_email = email.strip().lower()
        if not normalized_email or len(normalized_email) > 320 or "@" not in normalized_email:
            raise IdentityProviderError("OIDC email claim is invalid")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise IdentityProviderError("OIDC subject is invalid")
        display_name = effective.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = normalized_email.split("@", 1)[0]
        return IdentityClaim(
            provider=oidc_provider_key(settings.issuer),
            subject=subject,
            email_normalized=normalized_email,
            email_verified=True,
            display_name=display_name.strip()[:120],
        )

    @staticmethod
    def _verify_id_token(
        *,
        id_token: str,
        nonce: str,
        settings: OidcSettings,
        discovery: OidcDiscovery,
    ) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
            algorithm = header.get("alg")
            allowed = set(settings.allowed_algorithms)
            if discovery.signing_algorithms:
                allowed &= set(discovery.signing_algorithms)
            if algorithm not in allowed:
                raise IdentityProviderError("OIDC signing algorithm is not allowed")
            signing_key = get_signing_key(
                id_token,
                jwks_uri=discovery.jwks_uri,
                algorithm=algorithm,
                timeout_seconds=settings.timeout_seconds,
            )
            claims = jwt.decode(
                id_token,
                signing_key,
                algorithms=sorted(allowed),
                audience=settings.client_id,
                issuer=settings.issuer,
                leeway=30,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub", "nonce"],
                },
            )
        except IdentityProviderError:
            raise
        except (jwt.PyJWTError, ValueError) as exc:
            raise IdentityProviderError("OIDC ID token validation failed") from exc
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce):
            raise IdentityProviderError("OIDC nonce mismatch")
        audience = claims.get("aud")
        if (
            isinstance(audience, list)
            and len(audience) > 1
            and claims.get("azp") != settings.client_id
        ):
            raise IdentityProviderError("OIDC authorized party mismatch")
        return claims

    @staticmethod
    def _userinfo(
        *,
        endpoint: str | None,
        access_token: str,
        timeout: float,
    ) -> dict[str, Any] | None:
        if endpoint is None:
            return None
        try:
            response = httpx.get(
                endpoint,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityProviderError("OIDC userinfo request failed") from exc
        if not isinstance(payload, dict):
            raise IdentityProviderError("OIDC userinfo response is invalid")
        return payload
