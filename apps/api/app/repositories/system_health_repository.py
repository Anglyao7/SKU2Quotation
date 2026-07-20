from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    ready: bool
    migration_head: str
    reason: str | None = None


def check_database_readiness(
    session: Session,
    *,
    expected_migration_head: str,
) -> DatabaseReadiness:
    try:
        session.execute(text("SELECT 1"))
        current_head = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    except Exception:
        session.rollback()
        return DatabaseReadiness(
            ready=False,
            migration_head="unavailable",
            reason="DATABASE_UNAVAILABLE",
        )
    if expected_migration_head not in {"", "unknown"} and current_head != expected_migration_head:
        return DatabaseReadiness(
            ready=False,
            migration_head=str(current_head),
            reason="MIGRATION_HEAD_MISMATCH",
        )
    return DatabaseReadiness(ready=True, migration_head=str(current_head))
