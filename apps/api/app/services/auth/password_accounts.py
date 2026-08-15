"""Provision password-based identities for local development and Keycloak.

The application owns tenancy and role membership.  The configured identity
provider owns the password in production; the local profile stores an Scrypt
verifier solely so a newly created account is usable in the demo immediately.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...identity_models import LocalAccountCredentialRow, UserRow
from .contracts import IdentityProviderError
from .local_credentials import (
    new_local_password_material,
    normalize_local_identifier,
)
from .oidc_provider import OidcIdentityProviderAdapter


@dataclass(frozen=True)
class ProvisionedPasswordIdentity:
    user: UserRow
    local_credential: tuple[str, str] | None


class PasswordIdentityProvisioningError(ValueError):
    """Safe reason codes for account-provisioning use cases."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def password_is_valid(*, password: str, identifier: str, display_name: str) -> bool:
    """Validate the product's simple policy for newly provisioned accounts.

    Existing accounts may still have a legacy password and remain usable at
    login.  New accounts, however, are intentionally limited to six ASCII
    digits so an administrator can communicate an initial password reliably.
    ``identifier`` and ``display_name`` stay in the signature for callers that
    already provide them and for backwards compatibility with integrations.
    """

    del identifier, display_name
    return len(password) == 6 and password.isascii() and password.isdigit()


def provision_password_identity(
    session: Session,
    *,
    identifier: str,
    password: str,
    display_name: str,
    email: str | None,
    local_identity_provider: str = "local-password",
) -> ProvisionedPasswordIdentity:
    """Create an active identity, without adding its tenant membership yet."""

    configured_profile = os.getenv("AUTH_PROFILE", "local_fake").lower()
    if configured_profile == "local_fake":
        normalized_identifier = normalize_local_identifier(identifier)
        existing = session.scalar(
            select(LocalAccountCredentialRow.user_id).where(
                LocalAccountCredentialRow.identifier_normalized == normalized_identifier
            )
        )
        if existing is not None:
            raise PasswordIdentityProvisioningError("identifier_conflict")
        return ProvisionedPasswordIdentity(
            user=UserRow(
                id=uuid4(),
                email_normalized=email,
                display_name=display_name,
                identity_provider=local_identity_provider,
                identity_subject=str(uuid4()),
                status="active",
                is_platform_admin=False,
            ),
            local_credential=new_local_password_material(password),
        )
    if configured_profile == "enterprise_oidc":
        try:
            claim = OidcIdentityProviderAdapter().provision_password_user(
                identifier=identifier,
                password=password,
                display_name=display_name,
                email=email,
            )
        except IdentityProviderError as exc:
            raise PasswordIdentityProvisioningError("provider_rejected") from exc
        return ProvisionedPasswordIdentity(
            user=UserRow(
                id=uuid4(),
                email_normalized=claim.email_normalized,
                display_name=claim.display_name or display_name,
                identity_provider=claim.provider,
                identity_subject=claim.subject,
                status="active",
                is_platform_admin=False,
            ),
            local_credential=None,
        )
    raise PasswordIdentityProvisioningError("provider_unavailable")
