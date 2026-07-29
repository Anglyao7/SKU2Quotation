from __future__ import annotations

import codecs
import os
import socket
import struct
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from ..ports.file_scanner import FileScannerPort, FileScanResult


RESTRICTED_UPLOAD_MAX_BYTES = 250 * 1024 * 1024
RESTRICTED_XLSX_MAX_ENTRIES = 2_000
RESTRICTED_XLSX_MAX_ENTRY_BYTES = 250 * 1024 * 1024
RESTRICTED_XLSX_MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
RESTRICTED_XLSX_MAX_ENTRY_RATIO = 200
RESTRICTED_XLSX_MAX_TOTAL_RATIO = 100
_READ_CHUNK_BYTES = 64 * 1024
_XLSX_REQUIRED_MEMBERS = frozenset({"[content_types].xml", "xl/workbook.xml"})
_XLSX_FORBIDDEN_MEMBERS = (
    "xl/vbaproject.bin",
    "xl/activex/",
    "xl/embeddings/",
    "customui/",
)


def _rejected(code: str) -> FileScanResult:
    return FileScanResult(
        clean=False,
        engine=RestrictedSpreadsheetScanner.engine_name,
        signature=code,
        detail_code=code,
    )


def _safe_archive_name(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.endswith("/"):
        parts = parts[:-1]
    return (
        bool(normalized)
        and not normalized.startswith("/")
        and bool(parts)
        and not any(part in {"", ".", ".."} for part in parts)
    )


def _csv_is_decodable(path: Path) -> bool:
    """Validate the full stream without keeping the uploaded document in memory."""

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        try:
            with path.open("rb") as source:
                while chunk := source.read(_READ_CHUNK_BYTES):
                    if b"\x00" in chunk:
                        return False
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
            return True
        except UnicodeDecodeError:
            continue
    return False


class RestrictedSpreadsheetScanner:
    """Low-memory production scanner for the compact CSV/XLSX import surface.

    This is deliberately not an antivirus replacement. It narrows the accepted
    format surface and rejects active content and archive-amplification inputs
    before the parser sees them.
    """

    engine_name = "atc-restricted-spreadsheet-scanner-v1"

    def scan(self, path: Path) -> FileScanResult:
        try:
            byte_size = path.stat().st_size
        except OSError:
            return _rejected("RESTRICTED_FILE_UNREADABLE")
        if byte_size <= 0:
            return _rejected("RESTRICTED_FILE_EMPTY")
        if byte_size > RESTRICTED_UPLOAD_MAX_BYTES:
            return _rejected("RESTRICTED_FILE_TOO_LARGE")

        suffix = path.suffix.casefold()
        try:
            with path.open("rb") as source:
                signature = source.read(8)
        except OSError:
            return _rejected("RESTRICTED_FILE_UNREADABLE")

        if signature.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            return _rejected("RESTRICTED_OLE_FORBIDDEN")
        if suffix == ".csv":
            if signature.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                return _rejected("RESTRICTED_FORMAT_MISMATCH")
            if not _csv_is_decodable(path):
                return _rejected("RESTRICTED_CSV_INVALID")
            return FileScanResult(clean=True, engine=self.engine_name)
        if suffix != ".xlsx":
            return _rejected("RESTRICTED_FILE_TYPE_FORBIDDEN")
        if not signature.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            return _rejected("RESTRICTED_FORMAT_MISMATCH")
        return self._scan_xlsx(path)

    def _scan_xlsx(self, path: Path) -> FileScanResult:
        try:
            with ZipFile(path) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > RESTRICTED_XLSX_MAX_ENTRIES:
                    return _rejected("RESTRICTED_XLSX_ENTRY_LIMIT")

                names = {entry.filename.casefold() for entry in entries}
                if not _XLSX_REQUIRED_MEMBERS <= names:
                    return _rejected("RESTRICTED_XLSX_STRUCTURE_INVALID")

                total_size = 0
                total_compressed = 0
                for entry in entries:
                    name = entry.filename.casefold().replace("\\", "/")
                    if not _safe_archive_name(entry.filename):
                        return _rejected("RESTRICTED_XLSX_PATH_INVALID")
                    if entry.flag_bits & 0x1:
                        return _rejected("RESTRICTED_XLSX_ENCRYPTED")
                    if entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                        return _rejected("RESTRICTED_XLSX_COMPRESSION_INVALID")
                    if any(
                        name == forbidden or name.startswith(forbidden)
                        for forbidden in _XLSX_FORBIDDEN_MEMBERS
                    ):
                        return _rejected("RESTRICTED_XLSX_ACTIVE_CONTENT")
                    if entry.file_size > RESTRICTED_XLSX_MAX_ENTRY_BYTES:
                        return _rejected("RESTRICTED_XLSX_ENTRY_SIZE_LIMIT")
                    if entry.file_size and not entry.compress_size:
                        return _rejected("RESTRICTED_XLSX_COMPRESSION_RATIO")
                    if (
                        entry.compress_size
                        and entry.file_size / entry.compress_size
                        > RESTRICTED_XLSX_MAX_ENTRY_RATIO
                    ):
                        return _rejected("RESTRICTED_XLSX_COMPRESSION_RATIO")
                    total_size += entry.file_size
                    total_compressed += entry.compress_size
                    if total_size > RESTRICTED_XLSX_MAX_UNCOMPRESSED_BYTES:
                        return _rejected("RESTRICTED_XLSX_EXPANDED_SIZE_LIMIT")

                if (
                    total_size
                    and (
                        not total_compressed
                        or total_size / total_compressed
                        > RESTRICTED_XLSX_MAX_TOTAL_RATIO
                    )
                ):
                    return _rejected("RESTRICTED_XLSX_COMPRESSION_RATIO")

                # Reading through every entry verifies decompression and CRC
                # while retaining only one small chunk at a time.
                for entry in entries:
                    if entry.is_dir():
                        continue
                    with archive.open(entry, "r") as source:
                        while source.read(_READ_CHUNK_BYTES):
                            pass
        except (BadZipFile, OSError, RuntimeError, ValueError):
            return _rejected("RESTRICTED_XLSX_ARCHIVE_INVALID")
        return FileScanResult(clean=True, engine=self.engine_name)


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
    if profile == "restricted":
        runtime_profile = os.getenv("ATC_RUNTIME_PROFILE", "standard").lower()
        if app_env in {"production", "prod"} and runtime_profile != "compact":
            raise RuntimeError(
                "restricted file scanner is only allowed in compact production"
            )
        return RestrictedSpreadsheetScanner()
    raise RuntimeError(f"unsupported file scanner profile: {profile}")
