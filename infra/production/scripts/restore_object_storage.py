"""Verify and restore a portable MinIO bucket snapshot without deleting extras."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config


def _client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
    )


def _verified_blob(root: Path, entry: dict[str, Any]) -> Path:
    blob = (root / str(entry["blob"])).resolve()
    if root.resolve() not in blob.parents:
        raise ValueError("backup manifest contains an unsafe blob path")
    checksum = hashlib.sha256()
    size = 0
    with blob.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            checksum.update(chunk)
            size += len(chunk)
    if size != int(entry["size"]) or checksum.hexdigest() != entry["sha256"]:
        raise ValueError(f"backup blob verification failed for {entry['key']!r}")
    return blob


def restore(source: Path) -> int:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(
        manifest.get("objects"), list
    ):
        raise ValueError("unsupported object-storage backup manifest")
    configured_bucket = os.environ["OBJECT_STORAGE_BUCKET"]
    if manifest.get("bucket") != configured_bucket:
        raise ValueError("backup bucket does not match OBJECT_STORAGE_BUCKET")

    client = _client()
    existing = {row["Name"] for row in client.list_buckets().get("Buckets", [])}
    if configured_bucket not in existing:
        client.create_bucket(Bucket=configured_bucket)
    client.put_bucket_versioning(
        Bucket=configured_bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )

    restored = 0
    for entry in manifest["objects"]:
        blob = _verified_blob(source, entry)
        extra_args = dict(entry.get("metadata") or {})
        client.upload_file(
            str(blob),
            configured_bucket,
            str(entry["key"]),
            ExtraArgs=extra_args or None,
        )
        restored += 1
    return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default="/backup/minio")
    arguments = parser.parse_args()
    restored = restore(Path(arguments.source))
    print(json.dumps({"status": "completed", "restored": restored}, sort_keys=True))


if __name__ == "__main__":
    main()
