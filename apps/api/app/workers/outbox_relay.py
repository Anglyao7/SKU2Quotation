from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from ..adapters.outbox_publisher import get_outbox_publisher
from ..database import set_request_context
from ..ports.outbox import OutboxMessage, OutboxPublisherPort
from ..repositories.outbox_repository import (
    claim_outbox_event,
    load_outbox_event_for_update,
)


@dataclass(frozen=True, slots=True)
class OutboxRelayResult:
    status: str
    outcome: str
    event_id: UUID | None = None
    attempt_count: int = 0
    next_attempt_at: datetime | None = None


def _bind_relay_context(session: Session, tenant_id: UUID) -> None:
    set_request_context(
        session,
        organization_id=UUID(int=0),
        tenant_id=tenant_id,
        user_id=UUID(int=0),
    )


def _message(event: object) -> OutboxMessage:
    return OutboxMessage(
        event_id=event.id,
        tenant_id=event.tenant_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        aggregate_version=event.aggregate_version,
        payload=dict(event.payload),
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
    )


def relay_one_outbox_event(
    session: Session,
    *,
    tenant_id: UUID,
    relay_id: str,
    publisher: OutboxPublisherPort | None = None,
    event_id: UUID | None = None,
    now: datetime | None = None,
) -> OutboxRelayResult:
    now = now or datetime.now(UTC)
    publisher = publisher or get_outbox_publisher()
    lease_seconds = max(10, int(os.getenv("OUTBOX_RELAY_LEASE_SECONDS", "60")))
    _bind_relay_context(session, tenant_id)
    if event_id is not None:
        existing = load_outbox_event_for_update(
            session, tenant_id=tenant_id, event_id=event_id
        )
        if existing is not None and existing.status in {"PUBLISHED", "DEAD"}:
            session.rollback()
            return OutboxRelayResult(
                status=existing.status,
                outcome="ALREADY_PUBLISHED" if existing.status == "PUBLISHED" else "DEAD_LETTER",
                event_id=existing.id,
                attempt_count=existing.attempt_count,
            )
        session.rollback()
        _bind_relay_context(session, tenant_id)

    event = claim_outbox_event(
        session,
        tenant_id=tenant_id,
        now=now,
        relay_id=relay_id,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
        event_id=event_id,
    )
    if event is None:
        session.rollback()
        return OutboxRelayResult(status="IDLE", outcome="NO_DUE_EVENT")
    message = _message(event)
    claimed_event_id = event.id
    claimed_attempt = event.attempt_count
    session.commit()

    try:
        publisher.publish(message)
    except Exception as exc:
        session.rollback()
        _bind_relay_context(session, tenant_id)
        current = load_outbox_event_for_update(
            session, tenant_id=tenant_id, event_id=claimed_event_id
        )
        if current is None or current.status != "PROCESSING" or current.lease_owner != relay_id:
            session.rollback()
            return OutboxRelayResult(
                status="LEASE_LOST",
                outcome="PUBLISH_FAILED_AFTER_LEASE_LOSS",
                event_id=claimed_event_id,
                attempt_count=claimed_attempt,
            )
        terminal = current.attempt_count >= current.max_attempts
        current.status = "DEAD" if terminal else "FAILED"
        current.lease_owner = None
        current.lease_expires_at = None
        current.published_at = None
        current.last_error_code = "OUTBOX_PUBLISH_FAILED"
        current.last_error_message = f"Outbox publish failed: {type(exc).__name__}."
        current.dead_lettered_at = now if terminal else None
        current.available_at = now + timedelta(
            seconds=min(300, 2 ** max(0, current.attempt_count - 1))
        )
        session.commit()
        return OutboxRelayResult(
            status=current.status,
            outcome="DEAD_LETTERED" if terminal else "RETRY_SCHEDULED",
            event_id=current.id,
            attempt_count=current.attempt_count,
            next_attempt_at=None if terminal else current.available_at,
        )

    _bind_relay_context(session, tenant_id)
    current = load_outbox_event_for_update(
        session, tenant_id=tenant_id, event_id=claimed_event_id
    )
    if current is None or current.status != "PROCESSING" or current.lease_owner != relay_id:
        session.rollback()
        return OutboxRelayResult(
            status="LEASE_LOST",
            outcome="PUBLISHED_AT_LEAST_ONCE_REDELIVERY_REQUIRED",
            event_id=claimed_event_id,
            attempt_count=claimed_attempt,
        )
    current.status = "PUBLISHED"
    current.published_at = now
    current.lease_owner = None
    current.lease_expires_at = None
    current.dead_lettered_at = None
    current.last_error_code = None
    current.last_error_message = None
    session.commit()
    return OutboxRelayResult(
        status="PUBLISHED",
        outcome="PUBLISHED",
        event_id=current.id,
        attempt_count=current.attempt_count,
    )
