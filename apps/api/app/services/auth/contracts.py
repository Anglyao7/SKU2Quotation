from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IdentityClaim:
    provider: str
    subject: str
    email_normalized: str | None = None
    email_verified: bool = False
    display_name: str | None = None


class IdentityProviderPort(Protocol):
    provider_name: str

    def exchange_authorization_code(
        self,
        *,
        authorization_code: str,
        code_verifier: str,
        redirect_uri: str,
        nonce: str | None = None,
    ) -> IdentityClaim: ...

    def authenticate_password(
        self,
        *,
        identifier: str,
        password: str,
    ) -> IdentityClaim: ...

    def change_password(
        self,
        *,
        subject: str,
        new_password: str,
    ) -> None: ...

    def provision_password_user(
        self,
        *,
        identifier: str,
        password: str,
        display_name: str,
        email: str | None = None,
    ) -> IdentityClaim: ...


class IdentityProviderError(ValueError):
    pass


class IdentityProviderPasswordPolicyError(IdentityProviderError):
    pass
