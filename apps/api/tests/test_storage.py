from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from app.services.storage import store_upload_with_inspection


class _Upload:
    filename = "catalog.xlsx"
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._read = False
        self.closed = False

    async def read(self, _size: int) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._payload

    async def close(self) -> None:
        self.closed = True


class _Storage:
    backend_name = "test"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.payload = b""

    def put_file(
        self,
        source: Path,
        *,
        object_key: str,
        content_type: str | None,
    ) -> None:
        del object_key, content_type
        self.events.append("put")
        self.payload = source.read_bytes()


def test_upload_is_inspected_from_staging_before_object_storage() -> None:
    payload = b"PK\x03\x04catalog-payload"
    upload = _Upload(payload)
    events: list[str] = []
    storage = _Storage(events)

    def inspect(path: Path) -> tuple[int, bytes]:
        events.append("inspect")
        content = path.read_bytes()
        return len(content), content[:4]

    stored, inspection = asyncio.run(
        store_upload_with_inspection(
            upload,
            "SRC-TEST",
            tenant_id=UUID(int=2),
            storage=storage,
            inspect_staged=inspect,
        )
    )

    assert events == ["inspect", "put"]
    assert inspection == (len(payload), b"PK\x03\x04")
    assert storage.payload == payload
    assert stored.byte_size == len(payload)
    assert upload.closed is True
