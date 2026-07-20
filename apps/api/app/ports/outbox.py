from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    event_id: UUID
    tenant_id: UUID
    event_type: str
    schema_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    payload: dict[str, Any]
    correlation_id: str | None
    causation_id: str | None


class OutboxPublisherPort(Protocol):
    def publish(self, message: OutboxMessage) -> None:
        """Publish one event. Delivery may occur more than once."""

