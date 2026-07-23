from __future__ import annotations

from datetime import UTC, datetime, timedelta
import jwt
import pytest
import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.auth.contracts import (
    IdentityProviderError,
    IdentityProviderPasswordPolicyError,
)
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


def test_keycloak_password_change_uses_service_account_and_exact_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("KEYCLOAK_ADMIN_BASE_URL", raising=False)
    issuer = "https://identity.example.test/auth/realms/atc"
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
    requests: list[tuple[str, str, dict[str, object]]] = []

    def post(url: str, **kwargs: object) -> httpx.Response:
        requests.append(("POST", url, kwargs))
        if url == discovery.token_endpoint:
            return httpx.Response(
                200,
                json={
                    "access_token": "service-account-access-token",
                    "token_type": "Bearer",
                },
                request=httpx.Request("POST", url),
            )
        return httpx.Response(204, request=httpx.Request("POST", url))

    def put(url: str, **kwargs: object) -> httpx.Response:
        requests.append(("PUT", url, kwargs))
        return httpx.Response(204, request=httpx.Request("PUT", url))

    monkeypatch.setattr(
        "app.services.auth.oidc_provider.load_oidc_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.get_oidc_discovery",
        lambda *_args: discovery,
    )
    monkeypatch.setattr("app.services.auth.oidc_provider.httpx.post", post)
    monkeypatch.setattr("app.services.auth.oidc_provider.httpx.put", put)

    OidcIdentityProviderAdapter().change_password(
        subject="user/subject with spaces",
        new_password="UpdatedPass!456",
    )

    token_request = requests[0]
    assert token_request[0:2] == ("POST", discovery.token_endpoint)
    assert token_request[2]["auth"] == ("atc-web", "S" * 48)
    assert token_request[2]["data"] == {
        "grant_type": "client_credentials",
        "client_id": "atc-web",
    }
    logout_request = requests[1]
    reset_request = requests[2]
    expected_user_url = (
        "https://identity.example.test/auth/admin/realms/atc/"
        "users/user%2Fsubject%20with%20spaces"
    )
    assert logout_request[0:2] == ("POST", f"{expected_user_url}/logout")
    assert reset_request[0:2] == ("PUT", f"{expected_user_url}/reset-password")
    assert logout_request[2]["headers"]["Authorization"] == (
        "Bearer service-account-access-token"
    )
    assert reset_request[2]["json"] == {
        "type": "password",
        "temporary": False,
        "value": "UpdatedPass!456",
    }
    assert all(request[2]["follow_redirects"] is False for request in requests)


def test_keycloak_password_change_maps_policy_failure_without_upstream_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("KEYCLOAK_ADMIN_BASE_URL", raising=False)
    issuer = "https://identity.example.test/realms/atc"
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

    def post(url: str, **_kwargs: object) -> httpx.Response:
        if url == discovery.token_endpoint:
            return httpx.Response(
                200,
                json={"access_token": "service-token", "token_type": "Bearer"},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(
        "app.services.auth.oidc_provider.load_oidc_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.get_oidc_discovery",
        lambda *_args: discovery,
    )
    monkeypatch.setattr("app.services.auth.oidc_provider.httpx.post", post)
    monkeypatch.setattr(
        "app.services.auth.oidc_provider.httpx.put",
        lambda url, **_kwargs: httpx.Response(
            400,
            json={"errorMessage": "passwordHistory(secret detail)"},
            request=httpx.Request("PUT", url),
        ),
    )

    with pytest.raises(
        IdentityProviderPasswordPolicyError,
        match="password policy rejected",
    ) as exc_info:
        OidcIdentityProviderAdapter().change_password(
            subject="keycloak-user-id",
            new_password="UpdatedPass!456",
        )
    assert "passwordHistory" not in str(exc_info.value)


def test_password_management_rejects_non_keycloak_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = OidcSettings(
        issuer="https://identity.example.test/application/o/atc/",
        client_id="atc-web",
        client_secret="S" * 48,
        scopes=("openid", "profile", "email"),
        redirect_uris=("https://app.example.test/login/callback",),
        token_endpoint_auth_method="client_secret_basic",
        allowed_algorithms=("RS256",),
        allowed_endpoint_hosts=("identity.example.test",),
        timeout_seconds=5,
    )

    with pytest.raises(IdentityProviderError, match="does not support"):
        OidcIdentityProviderAdapter._keycloak_admin_realm_url(settings)


def test_managed_password_admin_endpoint_is_restricted_to_internal_keycloak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = OidcSettings(
        issuer="https://identity.example.test/realms/atc",
        client_id="atc-web",
        client_secret="S" * 48,
        scopes=("openid", "profile", "email"),
        redirect_uris=("https://app.example.test/login/callback",),
        token_endpoint_auth_method="client_secret_basic",
        allowed_algorithms=("RS256",),
        allowed_endpoint_hosts=("identity.example.test",),
        timeout_seconds=5,
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("KEYCLOAK_ADMIN_BASE_URL", "http://keycloak:8080")
    assert OidcIdentityProviderAdapter._keycloak_admin_realm_url(settings) == (
        "http://keycloak:8080/admin/realms/atc"
    )

    monkeypatch.setenv(
        "KEYCLOAK_ADMIN_BASE_URL",
        "https://identity.example.test",
    )
    with pytest.raises(IdentityProviderError, match="endpoint is invalid"):
        OidcIdentityProviderAdapter._keycloak_admin_realm_url(settings)


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
