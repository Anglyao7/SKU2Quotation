from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.services.auth.contracts import IdentityClaim
from app.services.auth.service import _activate_verified_invitation


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Scalar:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class _RecordingPostgresSession:
    def __init__(self) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.user = SimpleNamespace(
            id=uuid4(),
            display_name="Pending Owner",
        )
        self.membership = SimpleNamespace(id=uuid4())
        self.tenant = SimpleNamespace(id=uuid4())
        self.events: list[str] = []
        self.commit_count = 0
        self.rollback_count = 0

    def scalars(self, _statement: object) -> _Rows:
        self.events.append("pending-identity-query")
        return _Rows([self.user])

    def execute(
        self,
        statement: object,
        _parameters: dict[str, object] | None = None,
    ) -> _Rows | _Scalar:
        sql = str(statement)
        if "atc_lock_invitation_email" in sql:
            self.events.append("email-xact-lock")
            return _Scalar(None)
        if "atc_bind_oidc_invitation" in sql:
            self.events.append("bind-invitation")
            return _Scalar(True)
        self.events.append("tenant-invitation-query")
        return _Rows([(self.membership, self.tenant)])

    def expire(self, _instance: object) -> None:
        self.events.append("expire-user")

    def flush(self) -> None:
        self.events.append("flush")

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def test_first_oidc_binding_locks_email_before_invitation_queries() -> None:
    session = _RecordingPostgresSession()
    claim = IdentityClaim(
        provider=f"oidc:{'a' * 32}",
        subject="first-binding-subject",
        email_normalized="Owner@Example.test",
        email_verified=True,
        display_name="Verified Owner",
    )

    activated = _activate_verified_invitation(  # type: ignore[arg-type]
        session,
        claim=claim,
    )

    assert activated is session.user
    assert session.events[:4] == [
        "email-xact-lock",
        "pending-identity-query",
        "tenant-invitation-query",
        "bind-invitation",
    ]
    # pg_advisory_xact_lock must still belong to the surrounding login
    # transaction; login commits only after it creates the auth session.
    assert session.commit_count == 0
    assert session.rollback_count == 0
