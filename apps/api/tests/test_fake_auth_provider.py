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
