import os
from urllib.parse import urlparse

from .contracts import IdentityClaim, IdentityProviderError


def _allowed_redirect_hosts() -> set[str]:
    configured = {
        host.strip().lower().rstrip(".")
        for host in os.getenv("LOCAL_FAKE_REDIRECT_HOSTS", "").split(",")
        if host.strip()
    }
    return {"localhost", "127.0.0.1", "::1", *configured}


class FakeIdentityProviderAdapter:
    """Non-production authorization-code adapter for local and automated tests."""

    provider_name = "local_fake"

    def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
        code_verifier: str,
        redirect_uri: str,
        nonce: str | None = None,
    ) -> IdentityClaim:
        app_env = os.getenv("APP_ENV", "development").lower()
        profile = os.getenv("AUTH_PROFILE", "local_fake").lower()
        if app_env in {"production", "prod"} or profile != "local_fake":
            raise IdentityProviderError("fake identity provider is disabled")
        if len(code_verifier) < 43 or len(code_verifier) > 128:
            raise IdentityProviderError("invalid PKCE verifier")
        parsed = urlparse(redirect_uri)
        redirect_hostname = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or redirect_hostname not in _allowed_redirect_hosts()
        ):
            raise IdentityProviderError("redirect URI is not allowed")
        if not authorization_code.startswith("fake:"):
            raise IdentityProviderError("authorization code exchange failed")
        subject = authorization_code.removeprefix("fake:").strip()
        if not subject or len(subject) > 255:
            raise IdentityProviderError("authorization code exchange failed")
        return IdentityClaim(
            provider="local-bootstrap",
            subject=subject,
            email_verified=True,
        )

    def authenticate_password(
        self,
        *,
        identifier: str,
        password: str,
    ) -> IdentityClaim:
        del identifier, password
        raise IdentityProviderError(
            "password authentication is unavailable for the fake provider"
        )

    def change_password(
        self,
        *,
        subject: str,
        new_password: str,
    ) -> None:
        del subject, new_password
        raise IdentityProviderError(
            "password changes are unavailable for the fake provider"
        )
