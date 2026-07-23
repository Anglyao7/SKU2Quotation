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


class IdentityProviderError(ValueError):
    pass
