from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


INVITATION_EMAIL_LOCK_SQL = (
    "SELECT public.atc_lock_invitation_email(:normalized_email)"
)


def acquire_invitation_email_lock(
    session: Session,
    *,
    normalized_email: str,
) -> None:
    """Serialize invitation creation and first OIDC binding for one email.

    PostgreSQL transaction-level advisory locks remain held until the caller
    commits or rolls back.  The database helper owns normalization and lock-key
    derivation so every invitation path uses exactly the same key.
    """

    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    session.execute(
        text(INVITATION_EMAIL_LOCK_SQL),
        {"normalized_email": normalized_email},
    )
