from __future__ import annotations

from datetime import UTC, datetime, timedelta
import jwt
import pytest
import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.auth.contracts import IdentityProviderError
from app.services.auth.oidc_provider import (
    OidcDiscovery,
    OidcIdentityProviderAdapter,
    OidcSettings,
    _https_endpoint,
    _load_jwks,
    load_oidc_settings,
)


def test_oidc_settings_accept_standard_space_delimited_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OIDC_ISSUER",
        "https://identity.example.test/realms/atc",
    )
    monkeypatch.setenv("OIDC_CLIENT_ID", "atc-web")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "S" * 48)
    monkeypatch.setenv(
        "OIDC_REDIRECT_URIS",
        "https://app.example.test/login/callback",
    )
    monkeypatch.setenv("OIDC_SCOPES", "openid profile email")

    assert load_oidc_settings().scopes == ("openid", "profile", "email")


def test_oidc_id_token_requires_valid_signature_audience_issuer_and_nonce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issuer = "https://identity.example.test/application/o/atc/"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    settings = OidcSettings(
        issuer=issuer,
        client_id="atc-web",
        client_secret="S" * 48,
        scopes=("openid", "profile", "email"),
        redirect_uris=("https://app.example.test/login/callback",),
        token_endpoint_auth_method="client_secret_basic",
        allowed_algorithms=("RS256",),
        allowed_endpoint_hosts=("identity.example.test",),
        timeout_seconds=5,
    )
    discovery = OidcDiscovery(
        issuer=issuer,
        authorization_endpoint=f"{issuer}authorize",
        token_endpoint=f"{issuer}token",
        jwks_uri=f"{issuer}jwks",
        userinfo_endpoint=f"{issuer}userinfo",
        end_session_endpoint=f"{issuer}logout",
        signing_algorithms=("RS256",),
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.get_signing_key",
        lambda _token, **_kwargs: public_key,
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": "atc-web",
            "sub": "subject-1",
            "nonce": "N" * 43,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    claims = OidcIdentityProviderAdapter._verify_id_token(
        id_token=token,
        nonce="N" * 43,
        settings=settings,
        discovery=discovery,
    )
    assert claims["sub"] == "subject-1"

    with pytest.raises(IdentityProviderError, match="nonce"):
        OidcIdentityProviderAdapter._verify_id_token(
            id_token=token,
            nonce="X" * 43,
            settings=settings,
            discovery=discovery,
        )

    wrong_audience = jwt.encode(
        {
            "iss": issuer,
            "aud": "another-client",
            "sub": "subject-1",
            "nonce": "N" * 43,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    with pytest.raises(IdentityProviderError, match="validation"):
        OidcIdentityProviderAdapter._verify_id_token(
            id_token=wrong_audience,
            nonce="N" * 43,
            settings=settings,
            discovery=discovery,
        )


def test_oidc_password_grant_validates_tokens_without_exposing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issuer = "https://identity.example.test/realms/atc"
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    settings = OidcSettings(
        issuer=issuer,
        client_id="atc-web",
        client_secret="S" * 48,
        scopes=("openid", "profile", "email"),
        redirect_uris=("https://app.example.test/login/callback",),
        token_endpoint_auth_method="client_secret_basic",
        allowed_algorithms=("RS256",),
        allowed_endpoint_hosts=("identity.example.test",),
        timeout_seconds=5,
    )
    discovery = OidcDiscovery(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/authorize",
        token_endpoint=f"{issuer}/token",
        jwks_uri=f"{issuer}/jwks",
        userinfo_endpoint=None,
        end_session_endpoint=f"{issuer}/logout",
        signing_algorithms=("RS256",),
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": issuer,
            "aud": "atc-web",
            "sub": "password-subject",
            "email": "OWNER@EXAMPLE.TEST",
            "email_verified": True,
            "name": "Password Owner",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "password-key"},
    )
    captured: dict[str, object] = {}

    def token_request(url: str, **kwargs: object) -> httpx.Response:
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "access_token": "provider-access-token",
                "id_token": token,
                "token_type": "Bearer",
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(
        "app.services.auth.oidc_provider.load_oidc_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.get_oidc_discovery",
        lambda *_args: discovery,
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.get_signing_key",
        lambda _token, **_kwargs: public_key,
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.httpx.post",
        token_request,
    )

    claim = OidcIdentityProviderAdapter().authenticate_password(
        identifier="+8613800138000",
        password="correct horse battery staple",
    )

    assert claim.subject == "password-subject"
    assert claim.email_normalized == "owner@example.test"
    assert claim.email_verified is True
    assert captured["url"] == discovery.token_endpoint
    assert captured["auth"] == ("atc-web", "S" * 48)
    assert captured["follow_redirects"] is False
    assert captured["data"] == {
        "grant_type": "password",
        "client_id": "atc-web",
        "username": "+8613800138000",
        "password": "correct horse battery staple",
        "scope": "openid profile email",
    }


def test_oidc_discovery_endpoints_are_origin_allowlisted_and_jwks_never_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issuer = "https://identity.example.test/realms/atc"
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(IdentityProviderError, match="not trusted"):
        _https_endpoint(
            "https://metadata.internal.example/jwks",
            issuer=issuer,
            allowed_hosts=("identity.example.test",),
        )
    with pytest.raises(IdentityProviderError, match="not trusted"):
        _https_endpoint(
            "https://127.0.0.1/jwks",
            issuer=issuer,
            allowed_hosts=("127.0.0.1",),
        )

    redirect = httpx.Response(
        302,
        headers={"Location": "https://127.0.0.1/latest/meta-data/"},
        request=httpx.Request(
            "GET", "https://identity.example.test/redirecting-jwks"
        ),
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.httpx.get",
        lambda *_args, **_kwargs: redirect,
    )
    with pytest.raises(IdentityProviderError, match="retrieval"):
        _load_jwks(
            "https://identity.example.test/redirecting-jwks",
            5,
            force_refresh=True,
        )
