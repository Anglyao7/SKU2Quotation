from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FileScanResult:
    clean: bool
    engine: str
    signature: str | None = None
    detail_code: str = "CLEAN"


class FileScannerPort(Protocol):
    engine_name: str

    def scan(self, path: Path) -> FileScanResult: ...
