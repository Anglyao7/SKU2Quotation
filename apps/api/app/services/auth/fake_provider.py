import hmac
import os
from urllib.parse import urlparse

from ...constants import DEFAULT_OWNER_USER_ID
from .contracts import IdentityClaim, IdentityProviderError


LOCAL_OWNER_EMAIL = "owner@local.aitradecloud.invalid"
LOCAL_OWNER_PASSWORD = "zhimaoyun123"


def _allowed_redirect_hosts() -> set[str]:
    configured = {
        host.strip().lower().rstrip(".")
        for host in os.getenv("LOCAL_FAKE_REDIRECT_HOSTS", "").split(",")
        if host.strip()
    }
    return {"localhost", "127.0.0.1", "::1", *configured}


class FakeIdentityProviderAdapter:
    """Non-production identity adapter for local and automated tests."""

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
        app_env = os.getenv("APP_ENV", "development").lower()
        profile = os.getenv("AUTH_PROFILE", "local_fake").lower()
        if app_env in {"staging", "production", "prod"} or profile != "local_fake":
            raise IdentityProviderError("local identity provider is disabled")

        email = os.getenv("LOCAL_LOGIN_EMAIL", LOCAL_OWNER_EMAIL).strip().lower()
        account = os.getenv("LOCAL_LOGIN_ACCOUNT", "owner").strip().casefold()
        phone = os.getenv("LOCAL_LOGIN_PHONE", "").strip().casefold()
        submitted_identifier = identifier.strip().casefold()
        allowed_identifiers = tuple(
            candidate
            for candidate in (account, email.casefold(), phone)
            if candidate
        )
        identifier_matches = any(
            hmac.compare_digest(
                submitted_identifier.encode("utf-8"),
                candidate.encode("utf-8"),
            )
            for candidate in allowed_identifiers
        )
        expected_password = os.getenv(
            "LOCAL_LOGIN_PASSWORD",
            LOCAL_OWNER_PASSWORD,
        )
        password_matches = hmac.compare_digest(
            password.encode("utf-8"),
            expected_password.encode("utf-8"),
        )
        if not identifier_matches or not password_matches:
            raise IdentityProviderError("password authentication failed")

        return IdentityClaim(
            provider="local-bootstrap",
            subject=str(DEFAULT_OWNER_USER_ID),
            email_normalized=email,
            email_verified=True,
            display_name="Local Owner",
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

    def provision_password_user(
        self,
        *,
        identifier: str,
        password: str,
        display_name: str,
        email: str | None = None,
    ) -> IdentityClaim:
        del identifier, password, display_name, email
        raise IdentityProviderError(
            "local customer accounts are provisioned by the application"
        )
