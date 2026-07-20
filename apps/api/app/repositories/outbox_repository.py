from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..product_intelligence_models import OutboxEventRow


@dataclass(frozen=True, slots=True)
class OutboxMetrics:
    pending_count: int
    processing_count: int
    failed_count: int
    dead_count: int
    oldest_unpublished_at: datetime | None
    lag_seconds: float


def claim_outbox_event(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
    relay_id: str,
    lease_expires_at: datetime,
    event_id: UUID | None = None,
) -> OutboxEventRow | None:
    conditions = [
        OutboxEventRow.tenant_id == tenant_id,
        OutboxEventRow.deleted_at.is_(None),
        or_(
            and_(
                OutboxEventRow.status.in_(("PENDING", "FAILED")),
                OutboxEventRow.available_at <= now,
                OutboxEventRow.dead_lettered_at.is_(None),
            ),
            and_(
                OutboxEventRow.status == "PROCESSING",
                OutboxEventRow.lease_expires_at.is_not(None),
                OutboxEventRow.lease_expires_at <= now,
            ),
        ),
    ]
    if event_id is not None:
        conditions.append(OutboxEventRow.id == event_id)
    row = session.scalar(
        select(OutboxEventRow)
        .where(*conditions)
        .order_by(
            OutboxEventRow.available_at,
            OutboxEventRow.occurred_at,
            OutboxEventRow.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    row.status = "PROCESSING"
    row.attempt_count += 1
    row.lease_owner = relay_id
    row.lease_expires_at = lease_expires_at
    row.last_attempt_at = now
    row.last_error_code = None
    row.last_error_message = None
    return row


def load_outbox_event_for_update(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> OutboxEventRow | None:
    return session.scalar(
        select(OutboxEventRow)
        .where(
            OutboxEventRow.tenant_id == tenant_id,
            OutboxEventRow.id == event_id,
        )
        .with_for_update()
    )


def outbox_metrics(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime | None = None,
) -> OutboxMetrics:
    now = now or datetime.now(UTC)
    counts = dict(
        session.execute(
            select(OutboxEventRow.status, func.count())
            .where(OutboxEventRow.tenant_id == tenant_id)
            .group_by(OutboxEventRow.status)
        ).all()
    )
    oldest = session.scalar(
        select(func.min(OutboxEventRow.occurred_at)).where(
            OutboxEventRow.tenant_id == tenant_id,
            OutboxEventRow.status.in_(("PENDING", "PROCESSING", "FAILED")),
        )
    )
    if oldest is None:
        lag_seconds = 0.0
    else:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        lag_seconds = max(0.0, (now - oldest).total_seconds())
    return OutboxMetrics(
        pending_count=int(counts.get("PENDING", 0)),
        processing_count=int(counts.get("PROCESSING", 0)),
        failed_count=int(counts.get("FAILED", 0)),
        dead_count=int(counts.get("DEAD", 0)),
        oldest_unpublished_at=oldest,
        lag_seconds=lag_seconds,
    )
