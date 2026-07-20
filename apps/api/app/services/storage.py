import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from ..adapters.object_storage import get_object_storage
from ..ports.object_storage import ObjectStoragePort


MAX_UPLOAD_BYTES = 250 * 1024 * 1024
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


async def store_upload(
    upload: Any,
    source_id: str,
    *,
    tenant_id: UUID,
    storage: ObjectStoragePort | None = None,
) -> StoredUpload:
    storage = storage or get_object_storage()
    stored_filename = f"{source_id}{safe_suffix(upload.filename or '')}"
    object_key = f"tenants/{tenant_id}/quarantine/{stored_filename}"
    staging_root = Path(os.getenv("OBJECT_STORAGE_STAGING_DIR", tempfile.gettempdir()))
    staging_root.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="atc-upload-", suffix=safe_suffix(stored_filename), dir=staging_root)
    os.close(descriptor)
    target = Path(raw_path)
    digest = hashlib.sha256()
    size = 0

    try:
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadTooLargeError(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB 上限")
                digest.update(chunk)
                output.write(chunk)
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

    return StoredUpload(
        object_key=object_key,
        stored_filename=stored_filename,
        sha256=digest.hexdigest(),
        byte_size=size,
        declared_media_type=getattr(upload, "content_type", None),
    )
