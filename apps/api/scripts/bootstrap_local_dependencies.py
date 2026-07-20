"""Idempotently prepare local S3 and RabbitMQ dependencies."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import TypeVar

import boto3
import pika
from botocore.config import Config

from app.adapters.rabbitmq_topology import declare_product_topology


T = TypeVar("T")


def _retry(operation: Callable[[], T], *, attempts: int = 30) -> T:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # Dependency startup has provider-specific errors.
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(min(5.0, 0.5 * (attempt + 1)))
    raise RuntimeError("dependency bootstrap did not become ready") from last_error


def _bootstrap_object_storage() -> dict[str, str]:
    bucket = os.getenv("OBJECT_STORAGE_BUCKET", "atc-local-files")
    endpoint = os.environ["OBJECT_STORAGE_ENDPOINT_URL"]
    region = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")

    def create() -> dict[str, str]:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
        existing = {row["Name"] for row in client.list_buckets().get("Buckets", [])}
        if bucket not in existing:
            client.create_bucket(Bucket=bucket)
        client.put_bucket_versioning(
            Bucket=bucket,
            VersioningConfiguration={"Status": "Enabled"},
        )
        return {"bucket": bucket, "versioning": "enabled"}

    return _retry(create)


def _bootstrap_rabbitmq() -> dict[str, str]:
    url = os.environ["RABBITMQ_URL"]

    def create() -> dict[str, str]:
        connection = pika.BlockingConnection(pika.URLParameters(url))
        try:
            topology = declare_product_topology(connection.channel())
            return {
                "exchange": topology.exchange,
                "queue": topology.queue,
                "dead_letter_queue": topology.dead_letter_queue,
                "queue_type": topology.queue_type,
            }
        finally:
            connection.close()

    return _retry(create)


def main() -> None:
    print(
        json.dumps(
            {
                "status": "completed",
                "object_storage": _bootstrap_object_storage(),
                "rabbitmq": _bootstrap_rabbitmq(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
