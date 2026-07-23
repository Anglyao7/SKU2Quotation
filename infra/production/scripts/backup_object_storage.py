"""Create a portable, checksummed snapshot of the current MinIO bucket."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
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


def _json_metadata(head: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"Metadata": dict(head.get("Metadata", {}))}
    for name in (
        "ContentType",
        "CacheControl",
        "ContentDisposition",
        "ContentEncoding",
        "ContentLanguage",
    ):
        value = head.get(name)
        if isinstance(value, str) and value:
            result[name] = value
    return result


def backup(target: Path) -> dict[str, Any]:
    bucket = os.environ["OBJECT_STORAGE_BUCKET"]
    target.mkdir(parents=True, exist_ok=False)
    objects_dir = target / "objects"
    objects_dir.mkdir(mode=0o700)
    client = _client()
    manifest_objects: list[dict[str, Any]] = []

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for listed in page.get("Contents", []):
            key = str(listed["Key"])
            key_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
            relative_blob = Path("objects") / key_digest[:2] / key_digest
            blob = target / relative_blob
            blob.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = blob.with_suffix(".partial")
            response = client.get_object(Bucket=bucket, Key=key)
            checksum = hashlib.sha256()
            size = 0
            with temporary.open("xb") as destination:
                while chunk := response["Body"].read(1024 * 1024):
                    destination.write(chunk)
                    checksum.update(chunk)
                    size += len(chunk)
            response["Body"].close()
            if size != int(response["ContentLength"]):
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"size mismatch while backing up object {key!r}")
            temporary.replace(blob)
            head = client.head_object(Bucket=bucket, Key=key)
            manifest_objects.append(
                {
                    "key": key,
                    "blob": relative_blob.as_posix(),
                    "size": size,
                    "sha256": checksum.hexdigest(),
                    "etag": str(head.get("ETag", "")).strip('"'),
                    "last_modified": (
                        head["LastModified"].astimezone(UTC).isoformat()
                        if head.get("LastModified")
                        else None
                    ),
                    "metadata": _json_metadata(head),
                }
            )

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "bucket": bucket,
        "object_count": len(manifest_objects),
        "objects": manifest_objects,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default="/backup/minio")
    arguments = parser.parse_args()
    manifest = backup(Path(arguments.target))
    print(
        json.dumps(
            {
                "status": "completed",
                "bucket": manifest["bucket"],
                "object_count": manifest["object_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
