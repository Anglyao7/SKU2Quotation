from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

import app.adapters.file_scanner as scanner_module
from app.adapters.file_scanner import (
    RESTRICTED_UPLOAD_MAX_BYTES,
    RestrictedSpreadsheetScanner,
    get_file_scanner,
)


def _workbook(path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Product Name", "SKU", "Material"])
    worksheet.append(["Compact Product", "COMPACT-001", "Steel"])
    workbook.save(path)


def _minimal_archive(path: Path, **members: bytes) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("xl/workbook.xml", b"<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", b"<worksheet/>")
        for name, content in members.items():
            archive.writestr(name, content)


def test_restricted_scanner_accepts_only_safe_csv_and_xlsx(tmp_path: Path) -> None:
    scanner = RestrictedSpreadsheetScanner()
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(
        "Product Name,SKU\nCompact Product,COMPACT-001\n",
        encoding="utf-8",
    )
    assert scanner.scan(csv_path).clean is True

    xlsx_path = tmp_path / "products.xlsx"
    _workbook(xlsx_path)
    assert scanner.scan(xlsx_path).clean is True

    unknown = tmp_path / "products.pdf"
    unknown.write_bytes(b"%PDF-1.7\n")
    rejected = scanner.scan(unknown)
    assert rejected.clean is False
    assert rejected.detail_code == "RESTRICTED_FILE_TYPE_FORBIDDEN"


def test_restricted_scanner_rejects_size_ole_macros_and_mismatched_formats(
    tmp_path: Path,
) -> None:
    scanner = RestrictedSpreadsheetScanner()

    oversized = tmp_path / "oversized.csv"
    oversized.write_bytes(b"a" * (RESTRICTED_UPLOAD_MAX_BYTES + 1))
    assert scanner.scan(oversized).detail_code == "RESTRICTED_FILE_TOO_LARGE"

    ole = tmp_path / "legacy.xlsx"
    ole.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy")
    assert scanner.scan(ole).detail_code == "RESTRICTED_OLE_FORBIDDEN"

    macro = tmp_path / "macro.xlsx"
    _minimal_archive(macro, **{"xl/vbaProject.bin": b"macro"})
    assert scanner.scan(macro).detail_code == "RESTRICTED_XLSX_ACTIVE_CONTENT"

    disguised = tmp_path / "archive.csv"
    _minimal_archive(disguised)
    assert scanner.scan(disguised).detail_code == "RESTRICTED_FORMAT_MISMATCH"


def test_restricted_scanner_bounds_xlsx_entries_expansion_and_ratio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = RestrictedSpreadsheetScanner()
    xlsx_path = tmp_path / "bounded.xlsx"
    _minimal_archive(xlsx_path)

    monkeypatch.setattr(scanner_module, "RESTRICTED_XLSX_MAX_ENTRIES", 2)
    assert scanner.scan(xlsx_path).detail_code == "RESTRICTED_XLSX_ENTRY_LIMIT"

    monkeypatch.setattr(scanner_module, "RESTRICTED_XLSX_MAX_ENTRIES", 2_000)
    monkeypatch.setattr(
        scanner_module,
        "RESTRICTED_XLSX_MAX_UNCOMPRESSED_BYTES",
        16,
    )
    assert (
        scanner.scan(xlsx_path).detail_code
        == "RESTRICTED_XLSX_EXPANDED_SIZE_LIMIT"
    )

    monkeypatch.setattr(
        scanner_module,
        "RESTRICTED_XLSX_MAX_UNCOMPRESSED_BYTES",
        64 * 1024 * 1024,
    )
    ratio_path = tmp_path / "ratio.xlsx"
    _minimal_archive(
        ratio_path,
        **{"xl/worksheets/highly-compressible.xml": b"0" * (1024 * 1024)},
    )
    assert scanner.scan(ratio_path).detail_code == "RESTRICTED_XLSX_COMPRESSION_RATIO"


def test_restricted_scanner_is_only_available_to_compact_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FILE_SCANNER_PROFILE", "restricted")
    monkeypatch.setenv("ATC_RUNTIME_PROFILE", "standard")
    with pytest.raises(RuntimeError, match="only allowed in compact production"):
        get_file_scanner()

    monkeypatch.setenv("ATC_RUNTIME_PROFILE", "compact")
    assert isinstance(get_file_scanner(), RestrictedSpreadsheetScanner)
