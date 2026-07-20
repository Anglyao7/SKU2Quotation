from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..repositories.outbox_repository import outbox_metrics
from ..system_schemas import OutboxMetricsResponse


def get_outbox_metrics(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> OutboxMetricsResponse:
    if "system.settings_manage" not in permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            "system.settings_manage permission is required.",
            kind="forbidden",
        )
    metrics = outbox_metrics(session, tenant_id=tenant_id)
    return OutboxMetricsResponse(
        pending_count=metrics.pending_count,
        processing_count=metrics.processing_count,
        failed_count=metrics.failed_count,
        dead_count=metrics.dead_count,
        oldest_unpublished_at=metrics.oldest_unpublished_at,
        lag_seconds=metrics.lag_seconds,
    )
