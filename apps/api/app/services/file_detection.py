from pathlib import Path
from zipfile import BadZipFile, ZipFile

from ..models import FileDetectionResponse


OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
PDF_SIGNATURE = b"%PDF-"


def detect_file_type(
    filename: str,
    header: bytes,
    archive_names: set[str] | None = None,
) -> FileDetectionResponse:
    extension = Path(filename).suffix.lower()
    detected_type = "UNKNOWN"
    parser = "manual_review"

    if header.startswith(OLE_SIGNATURE):
        if extension in {".doc", ".docx"}:
            detected_type, parser = "OLE / Legacy DOC", "legacy_word_converter"
        else:
            detected_type, parser = "OLE / Legacy XLS", "xlrd"
    elif header.startswith(ZIP_SIGNATURES):
        names = archive_names or set()
        if any(name.startswith("xl/") for name in names):
            detected_type, parser = "OOXML / XLSX", "openpyxl"
        elif any(name.startswith("word/") for name in names):
            detected_type, parser = "OOXML / DOCX", "python-docx"
        elif any(name.startswith("ppt/") for name in names):
            detected_type, parser = "OOXML / PPTX", "python-pptx"
        else:
            mapping = {
                ".xlsx": ("OOXML / XLSX", "openpyxl"),
                ".docx": ("OOXML / DOCX", "python-docx"),
                ".pptx": ("OOXML / PPTX", "python-pptx"),
            }
            detected_type, parser = mapping.get(extension, ("ZIP / OOXML", "ooxml_inspector"))
    elif header.startswith(PDF_SIGNATURE):
        detected_type, parser = "PDF", "pymupdf"
    elif extension == ".csv" and b"\x00" not in header:
        detected_type, parser = "TEXT / CSV", "python-csv"

    expected = {
        ".xlsx": "OOXML / XLSX",
        ".xls": "OLE / Legacy XLS",
        ".docx": "OOXML / DOCX",
        ".doc": "OLE / Legacy DOC",
        ".pdf": "PDF",
        ".pptx": "OOXML / PPTX",
        ".csv": "TEXT / CSV",
    }.get(extension)
    matches = expected is None or detected_type == expected
    warning = None if matches else f"文件扩展名 {extension or '无'} 与真实格式 {detected_type} 不一致"
    return FileDetectionResponse(
        filename=filename,
        extension=extension,
        detected_type=detected_type,
        extension_matches=matches,
        parser=parser,
        warning=warning,
    )


def detect_file_path(path: Path, original_filename: str | None = None) -> FileDetectionResponse:
    with path.open("rb") as source:
        header = source.read(32)

    archive_names: set[str] | None = None
    if header.startswith(ZIP_SIGNATURES):
        try:
            with ZipFile(path) as archive:
                archive_names = set(archive.namelist())
        except (BadZipFile, OSError):
            archive_names = set()

    return detect_file_type(original_filename or path.name, header, archive_names)
