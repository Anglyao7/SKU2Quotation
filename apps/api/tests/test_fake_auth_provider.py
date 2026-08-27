import pytest

from app.services.auth.contracts import IdentityProviderError
from app.services.auth.fake_provider import FakeIdentityProviderAdapter


def test_local_fake_redirect_host_can_be_explicitly_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LOCAL_FAKE_REDIRECT_HOSTS",
        "100.111.4.117,ricardomacbook-air-1.tailc2d2a2.ts.net",
    )
    adapter = FakeIdentityProviderAdapter()

    claim = adapter.exchange_authorization_code(
        authorization_code="fake:local-user",
        code_verifier="A" * 43,
        redirect_uri="http://100.111.4.117:5173/login/callback",
    )

    assert claim.subject == "local-user"


def test_local_fake_redirect_host_remains_deny_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCAL_FAKE_REDIRECT_HOSTS", raising=False)
    adapter = FakeIdentityProviderAdapter()

    with pytest.raises(IdentityProviderError, match="redirect URI is not allowed"):
        adapter.exchange_authorization_code(
            authorization_code="fake:local-user",
            code_verifier="A" * 43,
            redirect_uri="http://100.111.4.117:5173/login/callback",
        )


def test_local_identity_adapter_uses_the_shared_password_login_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_PROFILE", "local_fake")
    monkeypatch.setenv("LOCAL_LOGIN_ACCOUNT", "merchant-owner")
    monkeypatch.setenv("LOCAL_LOGIN_EMAIL", "owner@local.aitradecloud.invalid")
    monkeypatch.setenv("LOCAL_LOGIN_PHONE", "13800138000")
    monkeypatch.setenv("LOCAL_LOGIN_PASSWORD", "merchant123")
    adapter = FakeIdentityProviderAdapter()

    for identifier in (
        "merchant-owner",
        "OWNER@LOCAL.AITRADECLOUD.INVALID",
        "13800138000",
    ):
        claim = adapter.authenticate_password(
            identifier=identifier,
            password="merchant123",
        )
        assert claim.provider == "local-bootstrap"
        assert claim.email_verified is True

    with pytest.raises(IdentityProviderError, match="authentication failed"):
        adapter.authenticate_password(
            identifier="merchant-owner",
            password="wrong-password",
        )


def test_password_login_request_trims_surrounding_password_whitespace() -> None:
    from app.auth_schemas import PasswordLoginRequest

    request = PasswordLoginRequest(
        grant_type="password",
        identifier="  merchant-owner  ",
        password="  merchant123  ",
    )

    assert request.identifier == "merchant-owner"
    assert request.password.get_secret_value() == "merchant123"
