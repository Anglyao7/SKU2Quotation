from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..repositories.public_catalog_repository import occupied_storefront_slugs
from ..tenant_slugs import unique_storefront_slug


def membership_storefront_path(
    *,
    account_scope: str,
    membership_id: UUID,
    tenant_slug: str,
    storefront_slug: str | None,
) -> str:
    """Return a customer-safe storefront path for a membership.

    Customer subaccounts must never fall back to the merchant's top-level
    storefront. The legacy account route remains a safe independent fallback
    while an older database is waiting for the storefront-slug migration.
    """

    tenant_path = str(tenant_slug or "").casefold().strip()
    account_path = str(storefront_slug or "").casefold().strip()
    if account_scope != "CUSTOMER_SUBACCOUNT":
        return f"/{tenant_path}" if tenant_path else "/"
    if account_path and account_path != tenant_path:
        return f"/{account_path}"
    legacy_key = f"account--{str(membership_id).casefold()}"
    return f"/{tenant_path}/account/{legacy_key}" if tenant_path else f"/{legacy_key}"


def _lock_allocation(session: Session) -> None:
    """Serialize storefront-path allocation across PostgreSQL API workers."""

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(487221302517390)"))


def allocate_storefront_slug(
    session: Session,
    *,
    base: str,
    exclude_tenant_id: UUID | None = None,
) -> str:
    _lock_allocation(session)
    return unique_storefront_slug(
        base,
        occupied_storefront_slugs(
            session,
            exclude_tenant_id=exclude_tenant_id,
        ),
    )


def exact_storefront_slug_is_available(session: Session, *, slug: str) -> bool:
    """Check an administrator-supplied path while holding the allocation lock."""

    _lock_allocation(session)
    return slug.casefold().strip() not in occupied_storefront_slugs(session)
