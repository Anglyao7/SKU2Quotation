from __future__ import annotations

import json
import os
from uuid import UUID

import pika

from app.adapters.rabbitmq_topology import declare_product_topology
from app.database import SessionLocal, set_request_context
from app.ports.outbox import OutboxMessage
from app.services.outbox_consumer import consume_product_committed_message


def _message(body: bytes) -> OutboxMessage:
    value = json.loads(body.decode("utf-8"))
    return OutboxMessage(
        event_id=UUID(value["event_id"]),
        tenant_id=UUID(value["tenant_id"]),
        event_type=value["event_type"],
        schema_version=int(value["schema_version"]),
        aggregate_type=value["aggregate_type"],
        aggregate_id=value["aggregate_id"],
        aggregate_version=int(value["aggregate_version"]),
        payload=value["payload"],
        correlation_id=value.get("correlation_id"),
        causation_id=value.get("causation_id"),
    )


def main() -> None:
    url = os.environ["RABBITMQ_URL"]
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()
    topology = declare_product_topology(channel)
    channel.basic_qos(prefetch_count=1)

    def consume(_channel: object, method: object, _properties: object, body: bytes) -> None:
        try:
            message = _message(body)
            with SessionLocal() as session:
                set_request_context(
                    session,
                    organization_id=UUID(int=0),
                    tenant_id=message.tenant_id,
                    user_id=UUID(int=0),
                )
                result = consume_product_committed_message(session, message=message)
                session.commit()
            if result.status == "COMPLETED":
                channel.basic_ack(delivery_tag=method.delivery_tag)
            else:
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        except Exception:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    channel.basic_consume(queue=topology.queue, on_message_callback=consume, auto_ack=False)
    try:
        channel.start_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
