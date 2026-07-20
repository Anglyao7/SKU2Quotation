"""Idempotent RabbitMQ declarations shared by bootstrap and consumers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RabbitMQTopology:
    exchange: str
    queue: str
    dead_letter_exchange: str
    dead_letter_queue: str
    queue_type: str
    delivery_limit: int


def topology_from_environment() -> RabbitMQTopology:
    queue_type = os.getenv("RABBITMQ_QUEUE_TYPE", "quorum").lower()
    if queue_type not in {"classic", "quorum"}:
        raise ValueError("RABBITMQ_QUEUE_TYPE must be classic or quorum")
    delivery_limit = int(os.getenv("RABBITMQ_DELIVERY_LIMIT", "5"))
    if delivery_limit < 1:
        raise ValueError("RABBITMQ_DELIVERY_LIMIT must be at least 1")
    return RabbitMQTopology(
        exchange=os.getenv("OUTBOX_EXCHANGE", "atc.domain-events"),
        queue=os.getenv("PRODUCT_EVENT_QUEUE", "atc.product-knowledge-projector-v1"),
        dead_letter_exchange=os.getenv("RABBITMQ_DEAD_LETTER_EXCHANGE", "atc.dead-letter"),
        dead_letter_queue=os.getenv(
            "RABBITMQ_DEAD_LETTER_QUEUE",
            "atc.product-knowledge-projector-v1.dlq",
        ),
        queue_type=queue_type,
        delivery_limit=delivery_limit,
    )


def queue_arguments(topology: RabbitMQTopology) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "x-dead-letter-exchange": topology.dead_letter_exchange,
    }
    if topology.queue_type == "quorum":
        arguments.update(
            {
                "x-queue-type": "quorum",
                "x-delivery-limit": topology.delivery_limit,
            }
        )
    return arguments


def declare_product_topology(channel: Any) -> RabbitMQTopology:
    topology = topology_from_environment()
    channel.exchange_declare(
        exchange=topology.exchange,
        exchange_type="topic",
        durable=True,
    )
    channel.exchange_declare(
        exchange=topology.dead_letter_exchange,
        exchange_type="fanout",
        durable=True,
    )
    channel.queue_declare(queue=topology.dead_letter_queue, durable=True)
    channel.queue_bind(
        queue=topology.dead_letter_queue,
        exchange=topology.dead_letter_exchange,
    )
    channel.queue_declare(
        queue=topology.queue,
        durable=True,
        arguments=queue_arguments(topology),
    )
    channel.queue_bind(
        queue=topology.queue,
        exchange=topology.exchange,
        routing_key="product.committed",
    )
    return topology
