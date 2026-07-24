from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class ObjectStoragePort(Protocol):
    backend_name: str

    def put_file(self, source: Path, *, object_key: str, content_type: str | None) -> None: ...

    def promote(self, *, quarantine_key: str, source_key: str) -> None: ...

    def exists(self, object_key: str) -> bool: ...

    def delete(self, object_key: str) -> None: ...

    def materialize(self, object_key: str) -> AbstractContextManager[Path]: ...

    def local_path(self, object_key: str) -> Path | None: ...
