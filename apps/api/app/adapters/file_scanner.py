from __future__ import annotations

import os
import socket
import struct
from pathlib import Path

from ..ports.file_scanner import FileScannerPort, FileScanResult


class DeterministicDevelopmentScanner:
    """Offline scanner for development/tests; never allowed in production."""

    engine_name = "atc-deterministic-development-scanner-v1"
    _SIGNATURES = {
        b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE": "EICAR-Test-Signature",
        b"ATC-MALWARE-TEST": "ATC-Test-Malware-Signature",
    }

    def scan(self, path: Path) -> FileScanResult:
        content = path.read_bytes()
        for marker, signature in self._SIGNATURES.items():
            if marker in content:
                return FileScanResult(
                    clean=False,
                    engine=self.engine_name,
                    signature=signature,
                    detail_code="MALWARE_DETECTED",
                )
        return FileScanResult(clean=True, engine=self.engine_name)


class ClamAVScannerAdapter:
    engine_name = "clamav-instream"

    def __init__(self, *, host: str, port: int, timeout_seconds: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def scan(self, path: Path) -> FileScanResult:
        with socket.create_connection(
            (self.host, self.port), timeout=self.timeout_seconds
        ) as connection:
            connection.sendall(b"zINSTREAM\0")
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    connection.sendall(struct.pack("!I", len(chunk)))
                    connection.sendall(chunk)
            connection.sendall(struct.pack("!I", 0))
            response = connection.recv(4096).decode("utf-8", errors="replace").strip("\0\r\n")
        if response.endswith("OK"):
            return FileScanResult(clean=True, engine=self.engine_name)
        if "FOUND" in response:
            signature = response.rsplit(":", 1)[-1].replace("FOUND", "").strip()
            return FileScanResult(
                clean=False,
                engine=self.engine_name,
                signature=signature or "MALWARE",
                detail_code="MALWARE_DETECTED",
            )
        raise RuntimeError("malware scanner returned an indeterminate result")


def get_file_scanner() -> FileScannerPort:
    profile = os.getenv("FILE_SCANNER_PROFILE", "development").lower()
    app_env = os.getenv("APP_ENV", "development").lower()
    if profile == "development":
        if app_env in {"production", "prod"}:
            raise RuntimeError("development file scanner is forbidden in production")
        return DeterministicDevelopmentScanner()
    if profile == "clamav":
        return ClamAVScannerAdapter(
            host=os.getenv("CLAMAV_HOST", "127.0.0.1"),
            port=int(os.getenv("CLAMAV_PORT", "3310")),
            timeout_seconds=float(os.getenv("CLAMAV_TIMEOUT_SECONDS", "30")),
        )
    raise RuntimeError(f"unsupported file scanner profile: {profile}")
