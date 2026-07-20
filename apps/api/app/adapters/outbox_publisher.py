from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from ..ports.outbox import OutboxMessage, OutboxPublisherPort


@dataclass(slots=True)
class InMemoryOutboxPublisher(OutboxPublisherPort):
    """Deterministic test/development publisher; forbidden in production."""

    messages: list[OutboxMessage] = field(default_factory=list)
    fail_with: Exception | None = None

    def publish(self, message: OutboxMessage) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.messages.append(message)


class RabbitMQOutboxPublisher(OutboxPublisherPort):
    def __init__(self, *, url: str, exchange: str) -> None:
        self.url = url
        self.exchange = exchange

    def publish(self, message: OutboxMessage) -> None:
        import pika

        connection = pika.BlockingConnection(pika.URLParameters(self.url))
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self.exchange,
                exchange_type="topic",
                durable=True,
            )
            channel.confirm_delivery()
            body = json.dumps(asdict(message), default=str, sort_keys=True).encode("utf-8")
            confirmed = channel.basic_publish(
                exchange=self.exchange,
                routing_key=message.event_type,
                body=body,
                mandatory=True,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                    message_id=str(message.event_id),
                    correlation_id=message.correlation_id,
                    type=message.event_type,
                    headers={
                        "tenant_id": str(message.tenant_id),
                        "schema_version": message.schema_version,
                    },
                ),
            )
            if confirmed is False:
                raise RuntimeError("RabbitMQ did not confirm the Outbox publication")
        finally:
            connection.close()


def get_outbox_publisher() -> OutboxPublisherPort:
    profile = os.getenv("OUTBOX_PUBLISHER_PROFILE", "memory").lower()
    environment = os.getenv("APP_ENV", "development").lower()
    if profile == "memory":
        if environment in {"production", "prod"}:
            raise RuntimeError("in-memory Outbox publisher is forbidden in production")
        return InMemoryOutboxPublisher()
    if profile == "rabbitmq":
        url = os.getenv("RABBITMQ_URL")
        if not url:
            raise RuntimeError("RABBITMQ_URL is required for the RabbitMQ Outbox publisher")
        return RabbitMQOutboxPublisher(
            url=url,
            exchange=os.getenv("OUTBOX_EXCHANGE", "atc.domain-events"),
        )
    raise RuntimeError(f"unsupported Outbox publisher profile: {profile}")
