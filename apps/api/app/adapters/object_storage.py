from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from ..ports.object_storage import ObjectStoragePort


def _safe_key(object_key: str) -> str:
    path = PurePosixPath(object_key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("unsafe object key")
    return path.as_posix()


class LocalObjectStorageAdapter:
    backend_name = "local-s3-compatible"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, object_key: str) -> Path:
        target = (self.root / Path(*PurePosixPath(_safe_key(object_key)).parts)).resolve()
        if self.root != target and self.root not in target.parents:
            raise ValueError("object key escaped storage root")
        return target

    def put_file(self, source: Path, *, object_key: str, content_type: str | None) -> None:
        del content_type
        target = self._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def promote(self, *, quarantine_key: str, source_key: str) -> None:
        source = self._path(quarantine_key)
        target = self._path(source_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not source.exists():
            return
        if not source.exists():
            raise FileNotFoundError("quarantine object is missing")
        shutil.copyfile(source, target)
        source.unlink()

    def delete(self, object_key: str) -> None:
        self._path(object_key).unlink(missing_ok=True)

    @contextmanager
    def materialize(self, object_key: str) -> Iterator[Path]:
        path = self._path(object_key)
        if not path.is_file():
            raise FileNotFoundError("object is missing")
        yield path

    def local_path(self, object_key: str) -> Path | None:
        return self._path(object_key)


class S3ObjectStorageAdapter:
    backend_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - production dependency guard
            raise RuntimeError("boto3 is required for OBJECT_STORAGE_BACKEND=s3") from exc
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
        )

    def put_file(self, source: Path, *, object_key: str, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else None
        self.client.upload_file(
            str(source),
            self.bucket,
            _safe_key(object_key),
            ExtraArgs=extra or {},
        )

    def promote(self, *, quarantine_key: str, source_key: str) -> None:
        quarantine_key = _safe_key(quarantine_key)
        source_key = _safe_key(source_key)
        self.client.copy_object(
            Bucket=self.bucket,
            Key=source_key,
            CopySource={"Bucket": self.bucket, "Key": quarantine_key},
        )
        self.client.delete_object(Bucket=self.bucket, Key=quarantine_key)

    def delete(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(object_key))

    @contextmanager
    def materialize(self, object_key: str) -> Iterator[Path]:
        suffix = Path(PurePosixPath(_safe_key(object_key)).name).suffix
        descriptor, raw_path = tempfile.mkstemp(prefix="atc-object-", suffix=suffix)
        os.close(descriptor)
        path = Path(raw_path)
        try:
            self.client.download_file(self.bucket, _safe_key(object_key), str(path))
            yield path
        finally:
            path.unlink(missing_ok=True)

    def local_path(self, object_key: str) -> Path | None:
        del object_key
        return None


def get_object_storage() -> ObjectStoragePort:
    backend = os.getenv("OBJECT_STORAGE_BACKEND", "local").lower()
    if backend == "local":
        root = Path(
            os.getenv(
                "OBJECT_STORAGE_LOCAL_ROOT",
                os.getenv(
                    "UPLOAD_DIR",
                    Path(__file__).resolve().parents[2] / "var" / "object-storage",
                ),
            )
        )
        return LocalObjectStorageAdapter(root)
    if backend == "s3":
        bucket = os.getenv("OBJECT_STORAGE_BUCKET")
        if not bucket:
            raise RuntimeError("OBJECT_STORAGE_BUCKET is required for S3 storage")
        return S3ObjectStorageAdapter(
            bucket=bucket,
            endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT_URL"),
            region_name=os.getenv("OBJECT_STORAGE_REGION"),
        )
    raise RuntimeError(f"unsupported object storage backend: {backend}")
