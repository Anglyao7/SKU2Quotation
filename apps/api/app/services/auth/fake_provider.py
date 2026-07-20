import os
from urllib.parse import urlparse

from .contracts import IdentityClaim, IdentityProviderError


class FakeIdentityProviderAdapter:
    """Non-production authorization-code adapter for local and automated tests."""

    provider_name = "local_fake"

    def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> IdentityClaim:
        app_env = os.getenv("APP_ENV", "development").lower()
        profile = os.getenv("AUTH_PROFILE", "local_fake").lower()
        if app_env in {"production", "prod"} or profile != "local_fake":
            raise IdentityProviderError("fake identity provider is disabled")
        if len(code_verifier) < 43 or len(code_verifier) > 128:
            raise IdentityProviderError("invalid PKCE verifier")
        parsed = urlparse(redirect_uri)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "localhost",
            "127.0.0.1",
        }:
            raise IdentityProviderError("redirect URI is not allowed")
        if not authorization_code.startswith("fake:"):
            raise IdentityProviderError("authorization code exchange failed")
        subject = authorization_code.removeprefix("fake:").strip()
        if not subject or len(subject) > 255:
            raise IdentityProviderError("authorization code exchange failed")
        return IdentityClaim(provider="local-bootstrap", subject=subject)
