import hashlib
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast
from uuid import UUID

from ..adapters.object_storage import get_object_storage
from ..ports.object_storage import ObjectStoragePort


MAX_UPLOAD_BYTES = 250 * 1024 * 1024
InspectionResult = TypeVar("InspectionResult")


class UploadTooLargeError(ValueError):
    pass


@dataclass(slots=True)
class StoredUpload:
    object_key: str
    stored_filename: str
    sha256: str
    byte_size: int
    declared_media_type: str | None


def safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".bin"


def upload_size_limit_bytes() -> int:
    """Return the application safety ceiling for every runtime profile.

    Compact previously had a much smaller 10 MiB ceiling even though uploads
    are streamed to disk and the reverse proxy already accepts large request
    bodies. Keeping one profile-independent limit prevents a file from working
    locally or in standard deployments but failing after a compact rollout.
    """

    return MAX_UPLOAD_BYTES


async def _store_upload(
    upload: Any,
    source_id: str,
    *,
    tenant_id: UUID,
    storage: ObjectStoragePort | None = None,
    inspect_staged: Callable[[Path], object] | None = None,
) -> tuple[StoredUpload, object | None]:
    storage = storage or get_object_storage()
    max_upload_bytes = upload_size_limit_bytes()
    stored_filename = f"{source_id}{safe_suffix(upload.filename or '')}"
    object_key = f"tenants/{tenant_id}/quarantine/{stored_filename}"
    staging_root = Path(os.getenv("OBJECT_STORAGE_STAGING_DIR", tempfile.gettempdir()))
    staging_root.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="atc-upload-", suffix=safe_suffix(stored_filename), dir=staging_root)
    os.close(descriptor)
    target = Path(raw_path)
    digest = hashlib.sha256()
    size = 0
    inspection: object | None = None

    try:
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_upload_bytes:
                    raise UploadTooLargeError(
                        f"文件超过 {max_upload_bytes // 1024 // 1024} MB 上限"
                    )
                digest.update(chunk)
                output.write(chunk)
        if inspect_staged is not None:
            inspection = inspect_staged(target)
        storage.put_file(
            target,
            object_key=object_key,
            content_type=getattr(upload, "content_type", None),
        )
    except Exception:
        raise
    finally:
        await upload.close()
        target.unlink(missing_ok=True)

    return (
        StoredUpload(
            object_key=object_key,
            stored_filename=stored_filename,
            sha256=digest.hexdigest(),
            byte_size=size,
            declared_media_type=getattr(upload, "content_type", None),
        ),
        inspection,
    )


async def store_upload(
    upload: Any,
    source_id: str,
    *,
    tenant_id: UUID,
    storage: ObjectStoragePort | None = None,
) -> StoredUpload:
    stored, _inspection = await _store_upload(
        upload,
        source_id,
        tenant_id=tenant_id,
        storage=storage,
    )
    return stored


async def store_upload_with_inspection(
    upload: Any,
    source_id: str,
    *,
    tenant_id: UUID,
    inspect_staged: Callable[[Path], InspectionResult],
    storage: ObjectStoragePort | None = None,
) -> tuple[StoredUpload, InspectionResult]:
    """Inspect the local upload once before sending it to object storage.

    S3-compatible storage cannot expose a local path. Inspecting the staging
    file avoids uploading a catalog and immediately downloading the same bytes
    again while the browser is still waiting for the HTTP response.
    """

    stored, inspection = await _store_upload(
        upload,
        source_id,
        tenant_id=tenant_id,
        storage=storage,
        inspect_staged=inspect_staged,
    )
    return stored, cast(InspectionResult, inspection)
