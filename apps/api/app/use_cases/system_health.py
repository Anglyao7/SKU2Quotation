from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..repositories.system_health_repository import check_database_readiness
from ..runtime_config import runtime_metadata


def liveness_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ai-trade-cloud-api",
        **runtime_metadata().as_dict(),
    }


def readiness_payload(session: Session) -> tuple[bool, dict[str, Any]]:
    metadata = runtime_metadata()
    database = check_database_readiness(
        session,
        expected_migration_head=metadata.migration_head,
    )
    ready = database.ready
    return ready, {
        "status": "ready" if ready else "not_ready",
        "service": "ai-trade-cloud-api",
        **metadata.as_dict(),
        "dependencies": {
            "database": {
                "status": "ready" if database.ready else "not_ready",
                "migration_head": database.migration_head,
                "reason": database.reason,
            }
        },
    }
