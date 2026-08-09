"""Versioned catalog language-package storage with an R2/S3 adapter."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote


IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _safe_key(object_key: str) -> str:
    path = PurePosixPath(object_key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("unsafe language package object key")
    return path.as_posix()


def _first_environment(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True, slots=True)
class LanguagePackageStorageStatus:
    backend: str
    configured: bool
    public_base_url: str | None
    fingerprint: str


@dataclass(frozen=True, slots=True)
class StoredLanguagePackage:
    object_key: str
    byte_size: int
    etag: str | None
    public_url: str | None


class LanguagePackageStorage:
    def __init__(self) -> None:
        requested_backend = _first_environment(
            "TRANSLATION_PACKAGE_STORAGE_BACKEND",
            "OBJECT_STORAGE_BACKEND",
        ).lower() or "local"
        self._requested_backend = requested_backend
        self.backend = "s3" if requested_backend == "r2" else requested_backend
        self.public_base_url = _first_environment(
            "TRANSLATION_PACKAGE_PUBLIC_BASE_URL",
        ).rstrip("/") or None
        self._local_root = Path(
            _first_environment(
                "TRANSLATION_PACKAGE_LOCAL_ROOT",
                "OBJECT_STORAGE_LOCAL_ROOT",
            )
            or Path(__file__).resolve().parents[2] / "var" / "language-packages"
        ).resolve()
        self._bucket = _first_environment(
            "TRANSLATION_PACKAGE_BUCKET",
            "OBJECT_STORAGE_BUCKET",
        )
        self._endpoint_url = _first_environment(
            "TRANSLATION_PACKAGE_ENDPOINT_URL",
            "OBJECT_STORAGE_ENDPOINT_URL",
        ) or None
        self._region = _first_environment(
            "TRANSLATION_PACKAGE_REGION",
            "OBJECT_STORAGE_REGION",
        ) or "auto"
        self._access_key_id = _first_environment(
            "TRANSLATION_PACKAGE_ACCESS_KEY_ID",
            "AWS_ACCESS_KEY_ID",
        ) or None
        self._secret_access_key = _first_environment(
            "TRANSLATION_PACKAGE_SECRET_ACCESS_KEY",
            "AWS_SECRET_ACCESS_KEY",
        ) or None
        self._client = None

    @property
    def status(self) -> LanguagePackageStorageStatus:
        configured = self.backend == "local" or bool(
            self.backend == "s3"
            and self._bucket
            and self._endpoint_url
            and self._access_key_id
            and self._secret_access_key
        )
        reported_backend = (
            "r2"
            if self._requested_backend == "r2"
            or (
                self.backend == "s3"
                and self._endpoint_url
                and ".r2.cloudflarestorage.com" in self._endpoint_url.casefold()
            )
            else self.backend
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "backend": reported_backend,
                    "bucket": self._bucket or None,
                    "endpoint_url": self._endpoint_url,
                    "local_root": (
                        str(self._local_root)
                        if self.backend == "local"
                        else None
                    ),
                    "public_base_url": self.public_base_url,
                    "region": self._region,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return LanguagePackageStorageStatus(
            backend=reported_backend,
            configured=configured,
            public_base_url=self.public_base_url,
            fingerprint=fingerprint,
        )

    def _path(self, object_key: str) -> Path:
        target = (
            self._local_root
            / Path(*PurePosixPath(_safe_key(object_key)).parts)
        ).resolve()
        if self._local_root != target and self._local_root not in target.parents:
            raise ValueError("language package key escaped storage root")
        return target

    def _s3_client(self):
        if self._client is not None:
            return self._client
        if not self.status.configured:
            raise RuntimeError("language package object storage is not configured")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("boto3 is required for R2 language packages") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
        )
        return self._client

    def public_url_for(self, object_key: str) -> str | None:
        if not self.public_base_url:
            return None
        encoded = "/".join(quote(part, safe="") for part in _safe_key(object_key).split("/"))
        return f"{self.public_base_url}/{encoded}"

    def put(self, content: bytes, *, object_key: str) -> StoredLanguagePackage:
        safe_key = _safe_key(object_key)
        if self.backend == "local":
            target = self._path(safe_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_path = tempfile.mkstemp(
                prefix="atc-language-pack-",
                dir=target.parent,
            )
            os.close(descriptor)
            staging = Path(raw_path)
            try:
                staging.write_bytes(content)
                os.replace(staging, target)
            finally:
                staging.unlink(missing_ok=True)
            return StoredLanguagePackage(
                object_key=safe_key,
                byte_size=len(content),
                etag=None,
                public_url=self.public_url_for(safe_key),
            )
        if self.backend != "s3":
            raise RuntimeError(
                f"unsupported language package storage backend: {self.backend}"
            )
        response = self._s3_client().put_object(
            Bucket=self._bucket,
            Key=safe_key,
            Body=content,
            ContentType="application/json; charset=utf-8",
            ContentEncoding="gzip",
            CacheControl=IMMUTABLE_CACHE_CONTROL,
        )
        return StoredLanguagePackage(
            object_key=safe_key,
            byte_size=len(content),
            etag=str(response.get("ETag") or "").strip() or None,
            public_url=self.public_url_for(safe_key),
        )

    def get(self, object_key: str) -> bytes:
        safe_key = _safe_key(object_key)
        if self.backend == "local":
            return self._path(safe_key).read_bytes()
        if self.backend != "s3":
            raise RuntimeError(
                f"unsupported language package storage backend: {self.backend}"
            )
        response = self._s3_client().get_object(
            Bucket=self._bucket,
            Key=safe_key,
        )
        return bytes(response["Body"].read())


def configured_language_package_storage() -> LanguagePackageStorage:
    storage = LanguagePackageStorage()
    if not storage.status.configured:
        raise RuntimeError("language package object storage is not configured")
    return storage


def language_package_storage_status() -> LanguagePackageStorageStatus:
    return LanguagePackageStorage().status
