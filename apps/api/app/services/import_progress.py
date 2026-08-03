from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import UUID


_PROGRESS_TTL_SECONDS = 6 * 60 * 60
_progress_lock = Lock()


@dataclass(frozen=True, slots=True)
class RuntimeImportProgress:
    progress: int
    stage: str
    processed_rows: int
    total_rows: int
    updated_at: float


_runtime_progress: dict[tuple[str, str], RuntimeImportProgress] = {}


def publish_runtime_import_progress(
    *,
    tenant_id: UUID,
    job_id: str,
    progress: int,
    stage: str,
    processed_rows: int = 0,
    total_rows: int = 0,
) -> None:
    """Expose worker progress without requiring a second database writer."""

    now = monotonic()
    state = RuntimeImportProgress(
        progress=max(0, min(100, progress)),
        stage=stage,
        processed_rows=max(0, processed_rows),
        total_rows=max(0, total_rows),
        updated_at=now,
    )
    with _progress_lock:
        stale_before = now - _PROGRESS_TTL_SECONDS
        for key, existing in tuple(_runtime_progress.items()):
            if existing.updated_at < stale_before:
                _runtime_progress.pop(key, None)
        _runtime_progress[(str(tenant_id), job_id)] = state


def get_runtime_import_progress(
    *,
    tenant_id: UUID,
    job_id: str,
) -> RuntimeImportProgress | None:
    with _progress_lock:
        return _runtime_progress.get((str(tenant_id), job_id))


def clear_runtime_import_progress(*, tenant_id: UUID, job_id: str) -> None:
    with _progress_lock:
        _runtime_progress.pop((str(tenant_id), job_id), None)
