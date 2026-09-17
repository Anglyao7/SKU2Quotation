from __future__ import annotations

import ipaddress
import os
import re
import socket
import unicodedata
from copy import copy
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import escape

import httpx
import reportlab
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from PIL import Image as PillowImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as ReportLabImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..public_catalog_schemas import PUBLIC_QUOTE_PDF_MAX_COLUMNS, PublicQuoteDocument
from .public_catalog_privacy import public_specification
from .carton_ordering import packing_quantity
from .quote_localization import (
    localize_quote_unit,
    proforma_text,
    quote_field_label,
    quote_headers,
    quote_is_rtl,
    quote_locale,
    quote_text,
)


QuoteImageLoader = Callable[[str], bytes | None]
QuoteDocumentType = Literal["quotation", "proforma_invoice", "packing_list"]
MAX_QUOTE_IMAGE_BYTES = 8 * 1024 * 1024
MAX_QUOTE_IMAGE_EDGE = 320
DEFAULT_QUOTE_HEADERS = quote_headers("zh-CN")
DEFAULT_QUOTE_WIDTHS = (
    8,
    15,
    20,
    36,
    12,
    12,
    14,
    22,
    14,
    14,
    15,
    17,
    17,
    18,
    38,
    32,
    26,
    28,
    18,
    16,
)


def _proforma_value(document: PublicQuoteDocument, field: str, fallback: object = "") -> object:
    settings = getattr(document.quote, "proforma_invoice", None)
    value = getattr(settings, field, None) if settings is not None else None
    return fallback if value in (None, "") else value


def _proforma_party_value(document: PublicQuoteDocument, field: str, fallback: object = "") -> object:
    value = getattr(document.quote.proforma_invoice, field, None)
    return fallback if value is None else value


def _proforma_number(document: PublicQuoteDocument) -> str:
    quote_number = str(document.quote.quote_number)
    fallback = (
        f"PI-{quote_number[3:]}"
        if quote_number.upper().startswith(("QD-", "QT-"))
        else f"PI-{quote_number}"
    )
    return str(_proforma_value(document, "invoice_number", fallback))


def _proforma_freight(document: PublicQuoteDocument) -> Decimal:
    try:
        return Decimal(str(_proforma_value(document, "freight", Decimal("0"))))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _quote_custom_fields(document: PublicQuoteDocument) -> list[object]:
    return [
        field for field in (getattr(document.quote, "custom_fields", None) or [])
        if str(getattr(field, "label", "")).strip()
    ]


def _quote_custom_value(field: object, item: object) -> str:
    values = getattr(field, "values", None) or {}
    return str(values.get(getattr(item, "id", None), "") or "").strip()

_LOGISTICS_OPTION_ALIASES: dict[str, tuple[str, ...]] = {
    "packing_quantity": (
        "装箱数量",
        "装箱数",
        "装箱量",
        "一箱个数",
        "每箱数量",
        "每箱个数",
        "qtyctn",
        "pcsctn",
        "packingquantity",
    ),
    "carton_dimensions": (
        "装箱尺寸",
        "外箱尺寸",
        "纸箱尺寸",
        "箱规",
        "cartonsize",
        "cartondimensions",
    ),
    "gross_weight": (
        "毛重",
        "箱毛重",
        "整箱毛重",
        "grossweight",
        "gw",
    ),
    "carton_volume": (
        "立方",
        "单箱立方",
        "箱体积",
        "cbm",
        "cartonvolume",
    ),
    "minimum_order_quantity": (
        "起订数",
        "起订量",
        "最低起订量",
        "最小起订量",
        "moq",
        "minimumorderquantity",
        "minimumquantity",
    ),
}


def _xlsx_text(value: object | None) -> str:
    """Force untrusted spreadsheet text to remain text, never a formula."""

    text = str(value or "")
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _xlsx_value(value: object | None) -> object:
    return _xlsx_text(value) if isinstance(value, str) else value


def _normalized_option_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s\-_/\\:：,.，。()（）\[\]【】]+", "", text)


def _option_value(item: object, field: str) -> object | None:
    values = getattr(item, "option_values_snapshot", None) or {}
    marker = values.get("_sku2quotation")
    source_values = (
        marker.get("quote_source_option_values")
        if isinstance(marker, dict)
        else None
    )
    if isinstance(source_values, dict):
        values = {**values, **source_values}
    normalized = {
        _normalized_option_key(key): value
        for key, value in values.items()
        if _normalized_option_key(key)
    }
    for alias in _LOGISTICS_OPTION_ALIASES[field]:
        value = normalized.get(_normalized_option_key(alias))
        if value not in (None, "", [], {}):
            return value
    return None


def _positive_decimal(value: object | None) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value > 0 else None
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    if match is None:
        return None
    try:
        number = Decimal(match.group(0))
    except InvalidOperation:
        return None
    return number if number > 0 else None


def _gross_weight_kg(value: object | None) -> Decimal | None:
    number = _positive_decimal(value)
    if number is None:
        return None
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    if "lb" in text or "磅" in text:
        return number * Decimal("0.45359237")
    if ("g" in text and "kg" not in text) or (
        "克" in text and "千克" not in text and "公斤" not in text
    ):
        return number / Decimal("1000")
    return number


def _carton_volume_m3(value: object | None) -> Decimal | None:
    number = _positive_decimal(value)
    if number is None:
        return None
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    if any(unit in text for unit in ("cm3", "cm³", "立方厘米")):
        return number / Decimal("1000000")
    if any(unit in text for unit in ("dm3", "dm³", "升")):
        return number / Decimal("1000")
    return number


def _dimensions_volume_m3(value: object | None) -> Decimal | None:
    if value in (None, ""):
        return None
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    numbers = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if len(numbers) < 3:
        return None
    dimensions = [Decimal(number) for number in numbers[:3]]
    volume = dimensions[0] * dimensions[1] * dimensions[2]
    if "mm" in text or "毫米" in text:
        return volume / Decimal("1000000000")
    if re.search(r"(?:^|[^c])m(?:$|[^a-z])", text) or (
        "米" in text and "厘米" not in text
    ):
        return volume
    # Carton dimensions are conventionally supplied in centimetres when the
    # unit is omitted.
    return volume / Decimal("1000000")


def _logistics_values(item: object) -> dict[str, object | None]:
    packing_raw = _option_value(item, "packing_quantity")
    dimensions_raw = _option_value(item, "carton_dimensions")
    gross_raw = _option_value(item, "gross_weight")
    volume_raw = _option_value(item, "carton_volume")
    moq_raw = _option_value(item, "minimum_order_quantity")
    packing = packing_quantity(getattr(item, "option_values_snapshot", {}))
    gross_weight = _gross_weight_kg(gross_raw)
    carton_volume = _carton_volume_m3(volume_raw) or _dimensions_volume_m3(
        dimensions_raw
    )
    quantity = Decimal(str(getattr(item, "quantity", 0) or 0))
    carton_factor = quantity / packing if packing and quantity >= 0 else None
    return {
        "carton_count": float(carton_factor) if carton_factor is not None else None,
        "packing_quantity": (
            float(packing) if packing is not None else _xlsx_value(packing_raw)
        ),
        "carton_dimensions": _xlsx_value(dimensions_raw),
        "gross_weight": (
            float(gross_weight)
            if gross_weight is not None
            else _xlsx_value(gross_raw)
        ),
        "carton_volume": (
            float(carton_volume)
            if carton_volume is not None
            else _xlsx_value(volume_raw)
        ),
        "total_volume": (
            float(carton_volume * carton_factor)
            if carton_volume is not None and carton_factor is not None
            else None
        ),
        "total_gross_weight": (
            float(gross_weight * carton_factor)
            if gross_weight is not None and carton_factor is not None
            else None
        ),
        "minimum_order_quantity": (
            float(moq)
            if (moq := _positive_decimal(moq_raw)) is not None
            else _xlsx_value(moq_raw)
        ),
    }


def _validate_public_image_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("unsupported quote image URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not allowed in quote image URLs")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in {80, 443}:
        raise ValueError("non-standard quote image ports are not allowed")
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("quote image host did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("quote image host is not public")


def fetch_remote_quote_image(url: str) -> bytes:
    """Fetch one public image with redirect, SSRF and size safeguards."""

    current = url
    timeout = httpx.Timeout(5.0, connect=3.0)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for _redirect in range(4):
            _validate_public_image_url(current)
            with client.stream(
                "GET",
                current,
                headers={"Accept": "image/*", "User-Agent": "AITradeCloud-Quote/1.0"},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("quote image redirect is missing a target")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").casefold()
                if content_type and not content_type.startswith("image/"):
                    raise ValueError("quote image URL did not return an image")
                declared_size = int(response.headers.get("content-length") or 0)
                if declared_size > MAX_QUOTE_IMAGE_BYTES:
                    raise ValueError("quote image exceeds the size limit")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_QUOTE_IMAGE_BYTES:
                        raise ValueError("quote image exceeds the size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ValueError("quote image exceeded the redirect limit")


def _normalized_quote_image(content: bytes) -> bytes:
    source_buffer = BytesIO(content)
    output = BytesIO()
    with PillowImage.open(source_buffer) as image:
        image.load()
        image.thumbnail((MAX_QUOTE_IMAGE_EDGE, MAX_QUOTE_IMAGE_EDGE))
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            image.convert("RGBA").save(output, format="PNG", optimize=True)
        else:
            image.convert("RGB").save(output, format="JPEG", quality=82, optimize=True)
    return output.getvalue()


def _place_quote_image(
    sheet: object,
    *,
    row_number: int,
    column_number: int,
    image_url: str | None,
    image_loader: QuoteImageLoader | None,
) -> bool:
    if not image_url or image_loader is None:
        return False
    try:
        content = image_loader(image_url)
        if not content:
            return False
        image = OpenpyxlImage(BytesIO(_normalized_quote_image(content)))
    except Exception:
        return False
    scale = min(86 / max(image.width, 1), 62 / max(image.height, 1))
    image.width = max(1, int(image.width * scale))
    image.height = max(1, int(image.height * scale))
    cell = sheet.cell(row_number, column_number)
    cell.value = None
    cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[row_number].height = max(
        sheet.row_dimensions[row_number].height or 0,
        52,
    )
    sheet.add_image(image, cell.coordinate)
    return True


def _configure_default_quote_printing(
    sheet: object,
    *,
    header_row: int,
    last_row: int,
) -> None:
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins.left = 0.2
    sheet.page_margins.right = 0.2
    sheet.page_margins.top = 0.35
    sheet.page_margins.bottom = 0.35
    sheet.print_options.horizontalCentered = True
    sheet.print_title_rows = f"1:{header_row}"
    sheet.print_area = f"A1:{get_column_letter(max(sheet.max_column, 1))}{last_row}"


def _apply_xlsx_grid_borders(
    sheet: object,
    *,
    min_row: int = 1,
    max_row: int | None = None,
    min_column: int = 1,
    max_column: int | None = None,
    color: str = "CBD5E1",
) -> None:
    """Give generated document spreadsheets a visible, print-friendly grid.

    The document workbench deliberately hides Excel's default gridlines.  That
    makes the on-screen preview cleaner, but it also meant downloaded XLSX
    files looked unformatted when opened or printed.  Apply a light border to
    every populated row, including blank cells inside that row, while keeping
    completely empty spacer rows unruined.

    Existing custom-template borders are preserved side by side; a missing
    side receives the shared light grid color so merchant templates retain
    their own stronger table styling where they already have it.
    """

    last_row = max_row if max_row is not None else int(getattr(sheet, "max_row", 0) or 0)
    last_column = max_column if max_column is not None else int(getattr(sheet, "max_column", 0) or 0)
    if last_row < min_row or last_column < min_column:
        return

    grid_side = Side(style="thin", color=color)
    for row_number in range(min_row, last_row + 1):
        row_cells = [
            sheet.cell(row_number, column_number)
            for column_number in range(min_column, last_column + 1)
        ]
        if not any(cell.value not in (None, "") for cell in row_cells):
            continue
        for cell in row_cells:
            existing = cell.border
            cell.border = Border(
                left=existing.left if existing.left.style else grid_side,
                right=existing.right if existing.right.style else grid_side,
                top=existing.top if existing.top.style else grid_side,
                bottom=existing.bottom if existing.bottom.style else grid_side,
                diagonal=existing.diagonal,
                diagonal_direction=existing.diagonal_direction,
                diagonalUp=existing.diagonalUp,
                diagonalDown=existing.diagonalDown,
                outline=existing.outline,
                vertical=existing.vertical,
                horizontal=existing.horizontal,
            )


def _template_item_value(field: str, document: PublicQuoteDocument, item) -> object:
    quote = document.quote
    locale = quote_locale(quote.locale)
    logistics = _logistics_values(item)
    values: dict[str, object | None] = {
        "serial_number": item.position,
        "sku_code": item.sku_code_snapshot,
        "product_name": item.name_snapshot,
        "description": item.description_snapshot,
        "specification": public_specification(item.specification_snapshot),
        "category": item.category_snapshot,
        "tags": quote_text(locale, "separator").join(item.tags_snapshot or []),
        "product_image": None,
        "quantity": float(item.quantity),
        "unit_code": localize_quote_unit(locale, item.unit_code_snapshot),
        **logistics,
        "unit_price": float(item.unit_price_snapshot),
        "line_total": float(item.line_total),
        "currency": item.currency_snapshot,
        "quote_number": quote.quote_number,
        "quote_date": quote.created_at.date(),
        "customer_name": quote.customer_name,
        "customer_company": quote.customer_company,
        "customer_email": quote.customer_email,
        "customer_phone": quote.customer_phone,
        "notes": quote.notes,
    }
    return _xlsx_value(values.get(field))


def _append_quote_extra_information(sheet: object, quote: object) -> None:
    """Append merchant-authored key/value notes without changing item rows.

    Custom quote templates are intentionally left intact above this section;
    the small block at the bottom gives merchants a safe place for delivery,
    payment, or lead-time notes without requiring another mapped column.
    """

    entries = getattr(quote, "extra_information", None) or []
    normalized: list[tuple[str, str]] = []
    for entry in entries:
        title = str(getattr(entry, "title", "") or "").strip()
        content = str(getattr(entry, "content", "") or "").strip()
        if title and content:
            normalized.append((title, content))
    if not normalized:
        return
    last_column = max(int(getattr(sheet, "max_column", 2) or 2), 2)
    sheet.append([])
    for title, content in normalized:
        sheet.append(
            [_xlsx_text(title), _xlsx_text(content)]
            + [None] * max(0, last_column - 2)
        )
        row_number = sheet.max_row
        if last_column > 2:
            sheet.merge_cells(
                start_row=row_number,
                start_column=2,
                end_row=row_number,
                end_column=last_column,
            )
        sheet.cell(row_number, 1).font = Font(bold=True)
        for cell in sheet[row_number]:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _copy_quote_template_cell_format(source: object, target: object) -> None:
    if getattr(source, "has_style", False):
        target._style = copy(source._style)
    target.font = copy(source.font)
    target.fill = copy(source.fill)
    target.border = copy(source.border)
    target.alignment = copy(source.alignment)
    target.protection = copy(source.protection)
    target.number_format = source.number_format


def _merge_quote_value(
    sheet: object,
    *,
    row: int,
    start_column: int,
    end_column: int,
    value: object,
) -> None:
    cell = sheet.cell(row, start_column)
    cell.value = _xlsx_value(value)
    if end_column > start_column:
        sheet.merge_cells(
            start_row=row,
            start_column=start_column,
            end_row=row,
            end_column=end_column,
        )


def _compose_system_quote_header(
    sheet: object,
    document: PublicQuoteDocument,
    *,
    column_count: int,
) -> int:
    """Render the system-owned document header above any product template."""

    quote = document.quote
    locale = quote_locale(quote.locale)
    column_count = max(4, column_count)
    last_column = get_column_letter(column_count)
    sheet.merge_cells(f"A1:{last_column}1")
    sheet["A1"] = quote_text(locale, "document_title")
    sheet["A1"].font = Font(size=18, bold=True, color="172033")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 32

    split_column = max(2, column_count // 2)
    right_label_column = split_column + 1
    right_value_column = min(column_count, right_label_column + 1)
    rows = (
        (
            quote_text(locale, "merchant"),
            document.tenant_name,
            quote_text(locale, "quote_number"),
            quote.quote_number,
        ),
        (
            quote_text(locale, "customer"),
            quote.customer_name,
            quote_text(locale, "date"),
            quote.created_at.date(),
        ),
        (
            quote_text(locale, "company"),
            quote.customer_company or "-",
            quote_text(locale, "currency"),
            quote.currency,
        ),
        (
            quote_text(locale, "email"),
            quote.customer_email or "-",
            quote_text(locale, "phone"),
            quote.customer_phone or "-",
        ),
    )
    for row_number, (left_label, left_value, right_label, right_value) in enumerate(
        rows,
        start=2,
    ):
        left_label_cell = sheet.cell(row_number, 1, left_label)
        left_label_cell.font = Font(bold=True, color="475569")
        left_label_cell.fill = PatternFill("solid", fgColor="F1F5F9")
        left_label_cell.alignment = Alignment(vertical="center")
        _merge_quote_value(
            sheet,
            row=row_number,
            start_column=2,
            end_column=split_column,
            value=left_value,
        )
        right_label_cell = sheet.cell(row_number, right_label_column, right_label)
        right_label_cell.font = Font(bold=True, color="475569")
        right_label_cell.fill = PatternFill("solid", fgColor="F1F5F9")
        right_label_cell.alignment = Alignment(vertical="center")
        _merge_quote_value(
            sheet,
            row=row_number,
            start_column=right_value_column,
            end_column=column_count,
            value=right_value,
        )
        for cell in sheet[row_number]:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.row_dimensions[row_number].height = 24
    sheet.cell(3, right_value_column).number_format = "yyyy-mm-dd"
    # One quiet spacer row separates document metadata from the product area.
    sheet.row_dimensions[6].height = 9
    return 7


def _copy_single_row_merges(
    source_sheet: object,
    target_sheet: object,
    *,
    source_row: int,
    target_row: int,
    source_to_target_columns: dict[int, int],
) -> None:
    for merged in source_sheet.merged_cells.ranges:
        if merged.min_row != source_row or merged.max_row != source_row:
            continue
        mapped_columns = [
            source_to_target_columns.get(column)
            for column in range(merged.min_col, merged.max_col + 1)
        ]
        if not mapped_columns or any(column is None for column in mapped_columns):
            continue
        target_sheet.merge_cells(
            start_row=target_row,
            start_column=min(mapped_columns),
            end_row=target_row,
            end_column=max(mapped_columns),
        )


def _render_custom_quote_xlsx(
    document: PublicQuoteDocument,
    *,
    template_path: Path,
    image_loader: QuoteImageLoader | None,
) -> bytes:
    spec = document.excel_template
    if spec is None:
        raise ValueError("custom quote template configuration is missing")
    source_workbook = load_workbook(
        template_path,
        data_only=False,
        keep_links=False,
    )
    try:
        if spec.sheet_name not in source_workbook.sheetnames:
            raise ValueError("configured quote worksheet is missing")
        source_sheet = source_workbook[spec.sheet_name]
        columns = sorted(spec.columns, key=lambda column: column.index)
        if not columns:
            raise ValueError("configured quote template has no product columns")
        custom_fields = _quote_custom_fields(document)

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = quote_text(
            quote_locale(document.quote.locale),
            "sheet_name",
        )[:31]
        sheet.sheet_view.showGridLines = False
        sheet.sheet_view.rightToLeft = quote_is_rtl(document.quote.locale)
        template_column_count = len(columns)
        product_column_count = template_column_count + len(custom_fields)
        sheet_column_count = max(4, product_column_count)
        product_header_row = _compose_system_quote_header(
            sheet,
            document,
            column_count=sheet_column_count,
        )
        source_to_target_columns = {
            column.index: target_index
            for target_index, column in enumerate(columns, start=1)
        }

        for target_index, column in enumerate(columns, start=1):
            source_letter = get_column_letter(column.index)
            target_letter = get_column_letter(target_index)
            source_dimension = source_sheet.column_dimensions[source_letter]
            target_dimension = sheet.column_dimensions[target_letter]
            target_dimension.width = source_dimension.width or 14
            target_dimension.hidden = source_dimension.hidden
            target_dimension.bestFit = source_dimension.bestFit

            source_header = source_sheet.cell(spec.header_row, column.index)
            target_header = sheet.cell(product_header_row, target_index)
            _copy_quote_template_cell_format(source_header, target_header)
            field = spec.column_mappings.get(column.key)
            target_header.value = (
                quote_field_label(document.quote.locale, field)
                if field
                else column.header
            )
            if not source_header.has_style:
                target_header.fill = PatternFill("solid", fgColor="172033")
                target_header.font = Font(color="FFFFFF", bold=True)
            target_header.alignment = copy(source_header.alignment)
            target_header.alignment = Alignment(
                horizontal=target_header.alignment.horizontal or "center",
                vertical=target_header.alignment.vertical or "center",
                wrap_text=True,
            )
        for offset, field in enumerate(custom_fields, start=1):
            target_index = template_column_count + offset
            sheet.column_dimensions[get_column_letter(target_index)].width = 22
            target_header = sheet.cell(product_header_row, target_index)
            target_header.value = str(field.label)
            target_header.fill = PatternFill("solid", fgColor="172033")
            target_header.font = Font(color="FFFFFF", bold=True)
            target_header.alignment = Alignment(
                horizontal="center",
                vertical="center",
                wrap_text=True,
            )
        source_header_dimension = source_sheet.row_dimensions[spec.header_row]
        sheet.row_dimensions[product_header_row].height = (
            source_header_dimension.height or 28
        )
        _copy_single_row_merges(
            source_sheet,
            sheet,
            source_row=spec.header_row,
            target_row=product_header_row,
            source_to_target_columns=source_to_target_columns,
        )

        data_start_row = product_header_row + 1
        source_data_dimension = source_sheet.row_dimensions[spec.data_start_row]
        total_volume = Decimal("0")
        total_gross_weight = Decimal("0")
        has_total_volume = False
        has_total_gross_weight = False
        item_count = max(1, len(document.quote.items))
        for offset in range(item_count):
            item = document.quote.items[offset] if document.quote.items else None
            row_number = data_start_row + offset
            sheet.row_dimensions[row_number].height = source_data_dimension.height
            for target_index, column in enumerate(columns, start=1):
                source_cell = source_sheet.cell(spec.data_start_row, column.index)
                target_cell = sheet.cell(row_number, target_index)
                _copy_quote_template_cell_format(source_cell, target_cell)
                field = spec.column_mappings.get(column.key)
                if field == "product_image" and item is not None:
                    target_cell.value = None
                    _place_quote_image(
                        sheet,
                        row_number=row_number,
                        column_number=target_index,
                        image_url=item.image_url_snapshot,
                        image_loader=image_loader,
                    )
                elif field and item is not None:
                    target_cell.value = _template_item_value(field, document, item)
                    if field in {
                        "unit_price",
                        "line_total",
                        "gross_weight",
                        "carton_volume",
                        "total_volume",
                        "total_gross_weight",
                    } and target_cell.number_format == "General":
                        target_cell.number_format = "#,##0.00"
                else:
                    target_cell.value = None
                target_cell.alignment = Alignment(
                    horizontal=target_cell.alignment.horizontal,
                    vertical=target_cell.alignment.vertical or "center",
                    wrap_text=True,
                )
            for custom_offset, field in enumerate(custom_fields, start=1):
                target_cell = sheet.cell(
                    row_number,
                    template_column_count + custom_offset,
                )
                target_cell.value = (
                    _quote_custom_value(field, item) if item is not None else None
                )
                target_cell.alignment = Alignment(
                    vertical="center",
                    wrap_text=True,
                )
            _copy_single_row_merges(
                source_sheet,
                sheet,
                source_row=spec.data_start_row,
                target_row=row_number,
                source_to_target_columns=source_to_target_columns,
            )
            if item is not None:
                logistics = _logistics_values(item)
                if isinstance(logistics["total_volume"], (int, float)):
                    total_volume += Decimal(str(logistics["total_volume"]))
                    has_total_volume = True
                if isinstance(logistics["total_gross_weight"], (int, float)):
                    total_gross_weight += Decimal(
                        str(logistics["total_gross_weight"])
                    )
                    has_total_gross_weight = True

        total_row = data_start_row + item_count
        field_columns = {
            spec.column_mappings.get(column.key): target_index
            for target_index, column in enumerate(columns, start=1)
            if spec.column_mappings.get(column.key)
        }
        for column_number in range(1, product_column_count + 1):
            cell = sheet.cell(total_row, column_number)
            cell.fill = PatternFill("solid", fgColor="EEF2F7")
            cell.font = Font(bold=True)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        total_value_column = field_columns.get("line_total", template_column_count)
        label_column = max(1, total_value_column - 1)
        sheet.cell(total_row, label_column).value = quote_text(
            document.quote.locale,
            "total",
        )
        sheet.cell(total_row, total_value_column).value = float(document.quote.total)
        sheet.cell(total_row, total_value_column).number_format = "#,##0.00"
        if has_total_volume and (column := field_columns.get("total_volume")):
            sheet.cell(total_row, column).value = float(total_volume)
            sheet.cell(total_row, column).number_format = "#,##0.00####"
        if has_total_gross_weight and (
            column := field_columns.get("total_gross_weight")
        ):
            sheet.cell(total_row, column).value = float(total_gross_weight)
            sheet.cell(total_row, column).number_format = "#,##0.00####"

        if document.quote.notes:
            sheet.append([])
            sheet.append(
                [
                    quote_text(document.quote.locale, "notes"),
                    _xlsx_text(document.quote.notes),
                ]
            )
            if sheet_column_count > 2:
                sheet.merge_cells(
                    start_row=sheet.max_row,
                    start_column=2,
                    end_row=sheet.max_row,
                    end_column=sheet_column_count,
                )
        _append_quote_extra_information(sheet, document.quote)
        product_last_column = get_column_letter(product_column_count)
        sheet.freeze_panes = f"A{data_start_row}"
        sheet.auto_filter.ref = (
            f"A{product_header_row}:{product_last_column}{data_start_row + item_count - 1}"
        )
        _apply_xlsx_grid_borders(sheet)
        _configure_default_quote_printing(
            sheet,
            header_row=product_header_row,
            last_row=sheet.max_row,
        )
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue()
    finally:
        source_workbook.close()


def _register_quote_pdf_font(locale: str) -> str:
    # Product data often keeps its original CJK text even when the document
    # chrome is English or another translated locale. Register the three CID
    # fallbacks for inline script runs, instead of selecting a font solely
    # from the requested document locale.
    for cid_font in ("STSong-Light", "HeiseiMin-W3", "HYSMyeongJo-Medium"):
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(cid_font))
        except KeyError:
            pass

    if locale in {"ar", "fa"}:
        configured = os.environ.get("QUOTE_ARABIC_FONT_PATH", "").strip()
        candidates = [
            *((Path(configured),) if configured else ()),
            Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                pdfmetrics.registerFont(TTFont("QuoteArabic", str(candidate)))
            except KeyError:
                pass
            return "QuoteArabic"

    vera = Path(reportlab.__file__).resolve().parent / "fonts" / "Vera.ttf"
    try:
        pdfmetrics.registerFont(TTFont("QuoteSans", str(vera)))
    except KeyError:
        pass
    return "QuoteSans"


def _pdf_localized_text(value: object | None, locale: str) -> str:
    text = str(value or "")
    if locale in {"ar", "fa"} and re.search(r"[\u0600-\u06ff]", text):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display

            text = get_display(arabic_reshaper.reshape(text))
        except ImportError:
            # Production installs the shaping helpers. This fallback keeps
            # development downloads functional before dependencies are synced.
            pass
    escaped = escape(text)
    # ReportLab's bundled Latin font cannot draw CJK characters. Keep it as
    # the base font so accented Latin remains intact, then apply script-aware
    # CID fallbacks only to the runs that need them. This also supports mixed
    # source data such as an English PI containing an untranslated Chinese
    # product or merchant name.
    script_fonts = (
        (r"([\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+)", "HYSMyeongJo-Medium"),
        (r"([\u3040-\u30ff\u31f0-\u31ff]+)", "HeiseiMin-W3"),
        (r"([\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff01-\uff60\uffe0-\uffe6]+)", "STSong-Light"),
    )
    for pattern, font_name in script_fonts:
        escaped = re.sub(pattern, rf'<font name="{font_name}">\1</font>', escaped)
    return escaped


_PUBLIC_QUOTE_TABLE_FIELDS = frozenset(
    {
        "serial_number",
        "sku_code",
        "product_name",
        "description",
        "specification",
        "category",
        "tags",
        "product_image",
        "quantity",
        "unit_code",
        "packing_quantity",
        "carton_count",
        "carton_dimensions",
        "gross_weight",
        "carton_volume",
        "minimum_order_quantity",
        "unit_price",
        "line_total",
        "total_volume",
        "total_gross_weight",
        "currency",
    }
)
_PUBLIC_QUOTE_DEFAULT_FIELDS = (
    "product_image",
    "product_name",
    "quantity",
    "carton_count",
    "unit_price",
    "line_total",
)
_PUBLIC_QUOTE_COLUMN_WIDTHS_MM = {
    "serial_number": 10,
    "sku_code": 32,
    "product_name": 42,
    "description": 38,
    "specification": 32,
    "category": 26,
    "tags": 28,
    "product_image": 20,
    "quantity": 18,
    "unit_code": 18,
    "packing_quantity": 22,
    "carton_count": 16,
    "carton_dimensions": 30,
    "gross_weight": 22,
    "carton_volume": 22,
    "minimum_order_quantity": 18,
    "unit_price": 25,
    "line_total": 28,
    "total_volume": 24,
    "total_gross_weight": 26,
    "currency": 18,
}
def _clip_quote_table_text(value: object | None, field: str) -> str:
    # Paragraph cells wrap naturally in the PDF.  Keep the complete imported
    # value instead of clipping it, otherwise logistics/specification details
    # disappear from an otherwise valid quotation.
    return str(value if value is not None else "").strip()


def _public_quote_table_fields(document: PublicQuoteDocument) -> list[str]:
    quote = document.quote
    configured = [
        str(field).strip()
        for field in (getattr(quote, "visible_columns", None) or [])
        if str(field).strip()
    ]
    template_fields: list[str] = []
    if document.excel_template is not None:
        for column in document.excel_template.columns:
            field = document.excel_template.column_mappings.get(column.key)
            if field:
                template_fields.append(str(field))
    candidates = configured or template_fields or list(_PUBLIC_QUOTE_DEFAULT_FIELDS)
    # The merchant controls the visible columns. SKU and logistics fields are
    # ordinary catalog data and are available when the default template is used.
    fields: list[str] = []
    for field in candidates:
        if field not in _PUBLIC_QUOTE_TABLE_FIELDS:
            continue
        if field not in fields:
            fields.append(field)
    return (fields or list(_PUBLIC_QUOTE_DEFAULT_FIELDS))[:PUBLIC_QUOTE_PDF_MAX_COLUMNS]


def _public_quote_table_headers(
    document: PublicQuoteDocument,
    fields: list[str],
    locale: str,
) -> list[str]:
    custom_headers: dict[str, str] = {}
    if document.excel_template is not None:
        for column in document.excel_template.columns:
            field = document.excel_template.column_mappings.get(column.key)
            header = str(column.header or "").strip()
            if field and header and field not in custom_headers:
                custom_headers[str(field)] = header
    headers: list[str] = []
    for field in fields:
        # System fields have one canonical translation dictionary.  Keeping a
        # merchant's source-language header here would make a PDF disagree
        # with the workbench and the generated/custom Excel document after the
        # quote language is changed.  Unknown fields (if a future template
        # exposes one) can still retain their custom header.
        localized = quote_field_label(locale, field)
        headers.append(localized or custom_headers.get(field) or field)
    return headers


def _quote_table_value(field: str, document: PublicQuoteDocument, item: object) -> str:
    value = _template_item_value(field, document, item)
    if value in (None, ""):
        return ""
    if field in {"quantity", "packing_quantity", "carton_count", "minimum_order_quantity"}:
        try:
            text = f"{Decimal(str(value)):f}"
            return text.rstrip("0").rstrip(".") if "." in text else text
        except (InvalidOperation, ValueError):
            return _clip_quote_table_text(value, field)
    if field in {
        "unit_price",
        "line_total",
        "gross_weight",
        "carton_volume",
        "total_volume",
        "total_gross_weight",
    }:
        try:
            return f"{Decimal(str(value)):,.2f}"
        except (InvalidOperation, ValueError):
            return _clip_quote_table_text(value, field)
    return _clip_quote_table_text(value, field)


def _quote_table_widths(fields: list[str]) -> list[float]:
    available = 178.0  # A4 width minus the 16 mm margins used below.
    widths = [float(_PUBLIC_QUOTE_COLUMN_WIDTHS_MM.get(field, 24)) for field in fields]
    total = sum(widths)
    if total <= available:
        return [width * mm for width in widths]
    scale = available / total
    scaled = [max(8.0, width * scale) for width in widths]
    overflow = sum(scaled) - available
    if overflow > 0:
        shrinkable = sum(max(width - 8.0, 0.0) for width in scaled)
        if shrinkable:
            scaled = [
                width - overflow * max(width - 8.0, 0.0) / shrinkable
                for width in scaled
            ]
    return [width * mm for width in scaled]


def _quote_pdf_image(
    image_url: str | None,
    image_loader: QuoteImageLoader | None,
    *,
    max_width: float,
    max_height: float,
) -> ReportLabImage | str:
    """Build a proportional thumbnail flowable for a PDF table cell.

    Images are loaded through the route-provided callback so private catalog
    media can be resolved with the same authorization as the quote download.
    The normalized in-memory copy keeps generated PDFs small and prevents a
    large source image from changing the table layout.
    """

    if not image_url or image_loader is None:
        return ""
    try:
        content = image_loader(image_url)
        if not content:
            return ""
        normalized = _normalized_quote_image(content)
        image_buffer = BytesIO(normalized)
        with PillowImage.open(image_buffer) as image_source:
            source_width, source_height = image_source.size
        if source_width <= 0 or source_height <= 0:
            return ""
        scale = min(
            max_width / source_width,
            max_height / source_height,
        )
        image_buffer.seek(0)
        image = ReportLabImage(
            image_buffer,
            width=max(1.0, source_width * scale),
            height=max(1.0, source_height * scale),
            hAlign="CENTER",
        )
        # Keep the BytesIO alive until reportlab has finished building the PDF.
        image._quote_image_buffer = image_buffer
        return image
    except Exception:
        return ""


def render_public_quote_draft_pdf(
    document: PublicQuoteDocument,
    *,
    image_loader: QuoteImageLoader | None = None,
    document_type: QuoteDocumentType = "quotation",
) -> bytes:
    if document_type == "packing_list":
        from .packing_list_documents import render_packing_list_pdf

        return render_packing_list_pdf(document, image_loader=image_loader)
    quote = document.quote
    locale = quote_locale(quote.locale)
    is_proforma = document_type == "proforma_invoice"
    document_title = (
        proforma_text(locale, "title")
        if is_proforma
        else quote_text(locale, "document_title")
    )
    document_number = _proforma_number(document) if is_proforma else quote.quote_number
    freight = _proforma_freight(document) if is_proforma else Decimal("0")
    font_name = _register_quote_pdf_font(locale)
    style_palette = {
        "indigo": {"accent": "#314B9B", "soft": "#EEF2FF", "border": "#CBD5E1"},
        "emerald": {"accent": "#087F5B", "soft": "#E8F7F0", "border": "#B7E4D2"},
        "gold": {"accent": "#8A6418", "soft": "#FBF3D7", "border": "#E4CF8A"},
        "slate": {"accent": "#334155", "soft": "#F1F5F9", "border": "#CBD5E1"},
        "rose": {"accent": "#9F3B5B", "soft": "#FFF0F4", "border": "#F0C4D2"},
    }
    palette = style_palette.get(document.style, style_palette["indigo"])
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    rtl = quote_is_rtl(locale)
    title_style = ParagraphStyle(
        "DraftLocalizedTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor(palette["accent"]),
        alignment=TA_RIGHT if rtl else styles["Title"].alignment,
    )
    body_style = ParagraphStyle(
        "DraftLocalizedBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9,
        leading=13,
        alignment=TA_RIGHT if rtl else styles["BodyText"].alignment,
    )
    right_style = ParagraphStyle("DraftRight", parent=body_style, alignment=TA_RIGHT)
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{document_title} {document_number}",
    )
    story = [
        Paragraph(_pdf_localized_text(document_title, locale), title_style),
        Spacer(1, 6 * mm),
    ]
    issue_date = _proforma_value(document, "issue_date", quote.created_at.date())
    if not is_proforma:
        metadata = [
            [
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'merchant')}: {document.tenant_name}", locale), body_style),
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'quote_number')}: {quote.quote_number}", locale), right_style),
            ],
            [
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'customer')}: {quote.customer_name}", locale), body_style),
                Paragraph("", right_style),
            ],
            [
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'company')}: {quote.customer_company or '-'}", locale), body_style),
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'date')}: {quote.created_at:%Y-%m-%d}", locale), right_style),
            ],
            [
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'email')}: {quote.customer_email or '-'}", locale), body_style),
                Paragraph(_pdf_localized_text(f"{quote_text(locale, 'currency')}: {quote.currency}", locale), right_style),
            ],
        ]
        meta_table = Table(metadata, colWidths=[90 * mm, 72 * mm])
        meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    if is_proforma:
        white_style = ParagraphStyle("InvoiceWhite", parent=body_style, textColor=colors.white)
        banner_style = ParagraphStyle("InvoiceBannerName", parent=white_style, alignment=TA_RIGHT, fontSize=13, leading=18)
        banner = Table([[Paragraph("PROFORMA INVOICE", white_style), Paragraph(_pdf_localized_text(_proforma_party_value(document, "seller_name", document.tenant_name), locale), banner_style)]], colWidths=[55*mm, 123*mm])
        banner.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1),colors.HexColor(palette["accent"])), ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("TOPPADDING",(0,0),(-1,-1),16), ("BOTTOMPADDING",(0,0),(-1,-1),16), ("LEFTPADDING",(0,0),(-1,-1),12), ("RIGHTPADDING",(0,0),(-1,-1),12)]))
        def party_paragraph(side):
            fallback_name = document.tenant_name if side == "seller" else quote.customer_company or quote.customer_name
            fallback_contact = "" if side == "seller" else quote.customer_name
            fallback_email = "" if side == "seller" else quote.customer_email or ""
            fallback_phone = "" if side == "seller" else quote.customer_phone or ""
            lines = [proforma_text(locale, side), str(_proforma_party_value(document, f"{side}_name", fallback_name) or "—")]
            for field, default in (("contact", fallback_contact), ("phone", fallback_phone), ("email", fallback_email), ("address", "")):
                label = proforma_text(locale, f"{side}_address") if field == "address" else quote_text(locale, field)
                lines.append(f"{label}: {_proforma_party_value(document, f'{side}_{field}', default) or '—'}")
            if side == "seller":
                for field, label in (("seller_website", proforma_text(locale, "website")), ("seller_tax_number", proforma_text(locale, "tax_id"))):
                    if _proforma_value(document, field):
                        lines.append(f"{label}: {_proforma_value(document, field)}")
            return Paragraph(_pdf_localized_text("\n".join(lines), locale).replace("\n", "<br/>"), body_style)
        party_table = Table([[party_paragraph("seller"), party_paragraph("buyer")]], colWidths=[89*mm, 89*mm], splitInRow=1)
        party_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor(palette["soft"])), ("LINEABOVE",(0,0),(-1,0),3,colors.HexColor(palette["accent"])), ("LINEAFTER",(0,0),(0,0),7,colors.white), ("VALIGN",(0,0),(-1,-1),"TOP"), ("TOPPADDING",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),10), ("LEFTPADDING",(0,0),(-1,-1),10), ("RIGHTPADDING",(0,0),(-1,-1),10)]))
        story = [banner, Spacer(1, 5*mm), Paragraph(_pdf_localized_text(document_title, locale), title_style), Paragraph(_pdf_localized_text(f"{document_number} · {issue_date}", locale), right_style), Spacer(1, 5*mm), party_table, Spacer(1, 6*mm)]
    else:
        story.extend([meta_table, Spacer(1, 7 * mm)])

    custom_fields = _quote_custom_fields(document)
    table_fields = ["serial_number", "product_name", "quantity", "unit_price", "line_total"] if is_proforma else _public_quote_table_fields(document)
    table_fields = [*table_fields, *[f"custom:{field.id}" for field in custom_fields]]
    table_body_style = ParagraphStyle(
        "DraftTableBody",
        parent=body_style,
        fontSize=7.8,
        leading=10,
        wordWrap="CJK",
        splitLongWords=1,
    )
    table_header_style = ParagraphStyle(
        "DraftTableHeader",
        parent=table_body_style,
        textColor=colors.white,
        fontName=font_name,
        fontSize=7.8,
        leading=9,
        alignment=TA_CENTER,
    )
    custom_labels = {f"custom:{field.id}": str(field.label) for field in custom_fields}
    base_field_count = len(table_fields) - len(custom_fields)
    table_headers = ([quote_field_label(locale, field) for field in table_fields[:base_field_count]] if is_proforma else _public_quote_table_headers(document, table_fields[:base_field_count], locale))
    table_headers.extend(custom_labels[field] for field in table_fields[base_field_count:])
    if is_proforma:
        table_headers[2] = f"{quote_text(locale, 'quantity')} / {quote_text(locale, 'unit')}"
    table_widths = _quote_table_widths(table_fields) if custom_fields else ([width * mm for width in (9, 79, 28, 30, 32)] if is_proforma else _quote_table_widths(table_fields))
    rows: list[list[object]] = [[
        Paragraph(_pdf_localized_text(header, locale), table_header_style)
        for header in table_headers
    ]]
    for item in quote.items:
        row: list[object] = []
        for index, field in enumerate(table_fields):
            if is_proforma and field == "product_name":
                product_text = "\n".join(filter(None, [item.name_snapshot, item.sku_code_snapshot, item.description_snapshot]))
                product_paragraph = Paragraph(_pdf_localized_text(product_text, locale).replace("\n", "<br/>"), table_body_style)
                thumbnail = _quote_pdf_image(item.image_url_snapshot, image_loader, max_width=12 * mm, max_height=12 * mm)
                if thumbnail:
                    product_cell = Table([[thumbnail, product_paragraph]], colWidths=[14 * mm, table_widths[index] - 19 * mm])
                    product_cell.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
                    row.append(product_cell)
                else:
                    row.append(product_paragraph)
            elif is_proforma and field == "quantity":
                row.append(Paragraph(_pdf_localized_text(f"{_quote_table_value(field, document, item)} / {localize_quote_unit(locale, item.unit_code_snapshot)}", locale), table_body_style))
            elif field == "product_image":
                row.append(
                    _quote_pdf_image(
                        item.image_url_snapshot,
                        image_loader,
                        max_width=max(4 * mm, table_widths[index] - 2 * mm),
                        max_height=18 * mm,
                    )
                )
            elif field.startswith("custom:"):
                custom_field = next((entry for entry in custom_fields if f"custom:{entry.id}" == field), None)
                row.append(Paragraph(_pdf_localized_text(_quote_custom_value(custom_field, item) if custom_field else "", locale), table_body_style))
            else:
                row.append(
                    Paragraph(
                        _pdf_localized_text(
                            _quote_table_value(field, document, item),
                            locale,
                        ),
                        table_body_style,
                    )
                )
        rows.append(row)
    totals = (
        [
            (proforma_text(locale, "subtotal"), Decimal(quote.total)),
            (proforma_text(locale, "freight"), freight),
            (proforma_text(locale, "grand_total"), Decimal(quote.total) + freight),
        ]
        if is_proforma
        else [(quote_text(locale, "total"), Decimal(quote.total))]
    )
    total_label_style = ParagraphStyle("InvoiceTotalLabel", parent=table_header_style, alignment=TA_RIGHT)
    for label, amount in totals:
        total_row = [""] * len(table_fields)
        total_row[0 if is_proforma else max(0, len(table_fields) - 2)] = Paragraph(
            _pdf_localized_text(label, locale),
            total_label_style if is_proforma else table_body_style,
        )
        total_row[-1] = Paragraph(
            _pdf_localized_text(f"{quote.currency} {amount:,.2f}", locale),
            table_header_style if is_proforma else table_body_style,
        )
        rows.append(total_row)
    numeric_indexes = {
        index for index, field in enumerate(table_fields)
        if field in {
            "quantity",
            "packing_quantity",
            "gross_weight",
            "carton_volume",
            "minimum_order_quantity",
            "unit_price",
            "line_total",
            "total_volume",
            "total_gross_weight",
        }
    }
    numeric_commands = [
        ("ALIGN", (index, 1), (index, -1), "RIGHT")
        for index in sorted(numeric_indexes)
    ]
    serial_index = table_fields.index("serial_number") if "serial_number" in table_fields else None
    if serial_index is not None:
        numeric_commands.append(("ALIGN", (serial_index, 1), (serial_index, -1), "CENTER"))
    table = Table(
        rows,
        repeatRows=1,
        colWidths=table_widths,
        splitInRow=1 if is_proforma else 0,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette["accent"])),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -4 if is_proforma else -2), 0.35, colors.HexColor(palette["border"])),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(palette["soft"])),
                *([("BACKGROUND", (0, -3), (-1, -1), colors.HexColor(palette["accent"]))] if is_proforma else []),
                *([("SPAN", (0, row), (-2, row)) for row in (-3, -2, -1)] if is_proforma else []),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                *numeric_commands,
            ]
        )
    )
    story.append(table)
    if is_proforma:
        section_style = ParagraphStyle(
            "DraftSection",
            parent=body_style,
            fontName=font_name,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor(palette["accent"]),
        )
        def details_grid(entries, columns):
            cells = [
                Paragraph(_pdf_localized_text(f"{label}\n{value}", locale).replace("\n", "<br/>"), table_body_style)
                for label, value in entries if value
            ]
            rows = [cells[index:index + columns] for index in range(0, len(cells), columns)]
            rows[-1].extend([""] * (columns - len(rows[-1])))
            grid = Table(rows, colWidths=[178 * mm / columns] * columns, splitInRow=1)
            grid.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), .3, colors.HexColor(palette["border"])),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            return grid

        trade_rows = [
            (proforma_text(locale, "incoterm"), _proforma_value(document, "incoterm")),
            (proforma_text(locale, "payment_terms"), _proforma_value(document, "payment_terms")),
            (proforma_text(locale, "delivery_terms"), _proforma_value(document, "delivery_terms")),
            (proforma_text(locale, "shipment_method"), _proforma_value(document, "shipment_method")),
            (proforma_text(locale, "port_of_loading"), _proforma_value(document, "port_of_loading")),
            (proforma_text(locale, "port_of_destination"), _proforma_value(document, "port_of_destination")),
        ]
        populated_trade_rows = [(label, str(value)) for label, value in trade_rows if value]
        if populated_trade_rows:
            story.extend([
                Spacer(1, 6 * mm),
                Paragraph(_pdf_localized_text(proforma_text(locale, "trade_terms"), locale), section_style),
                Spacer(1, 2 * mm),
            ])
            story.append(details_grid(populated_trade_rows, 3))

        bank_is_configured = any(
            _proforma_value(document, field)
            for field in ("beneficiary_name", "bank_name", "bank_address", "bank_account_number", "swift_code")
        )
        if bank_is_configured:
            bank_rows = [
                (proforma_text(locale, "beneficiary_name"), _proforma_value(document, "beneficiary_name", _proforma_party_value(document, "seller_name", document.tenant_name))),
                (proforma_text(locale, "bank_name"), _proforma_value(document, "bank_name")),
                (proforma_text(locale, "bank_address"), _proforma_value(document, "bank_address")),
                (proforma_text(locale, "bank_account_number"), _proforma_value(document, "bank_account_number")),
                (proforma_text(locale, "swift_code"), _proforma_value(document, "swift_code")),
            ]
            story.extend([
                Spacer(1, 6 * mm),
                Paragraph(_pdf_localized_text(proforma_text(locale, "bank_details"), locale), section_style),
                Spacer(1, 2 * mm),
            ])
            story.append(details_grid(bank_rows, 2))

        remarks = str(_proforma_value(document, "remarks")).strip()
        if remarks:
            story.extend([
                Spacer(1, 5 * mm),
                Paragraph(
                    _pdf_localized_text(f"{proforma_text(locale, 'remarks')}: {remarks}", locale),
                    body_style,
                ),
            ])
    if quote.notes:
        story.extend(
            [Spacer(1, 7 * mm), Paragraph(_pdf_localized_text(f"{quote_text(locale, 'notes')}: {quote.notes}", locale), body_style)]
        )
    for entry in getattr(quote, "extra_information", None) or []:
        title = str(getattr(entry, "title", "") or "").strip()
        content = str(getattr(entry, "content", "") or "").strip()
        if not title or not content:
            continue
        story.extend(
            [
                Spacer(1, 3 * mm),
                Paragraph(
                    _pdf_localized_text(f"{title}: {content}", locale),
                    body_style,
                ),
            ]
        )
    if not is_proforma:
        story.extend(
            [
                Spacer(1, 8 * mm),
                Paragraph(
                    _pdf_localized_text(
                        f"{quote_text(locale, 'merchant_contact')}: "
                        f"{document.contact_email or '-'}  {document.contact_phone or ''}",
                        locale,
                    ),
                    body_style,
                ),
            ]
        )
    pdf.build(story)
    return buffer.getvalue()


def _render_public_proforma_invoice_xlsx(
    document: PublicQuoteDocument,
    *,
    image_loader: QuoteImageLoader | None = None,
) -> bytes:
    quote = document.quote
    locale = quote_locale(quote.locale)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = proforma_text(locale, "sheet_name")[:31]
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.rightToLeft = quote_is_rtl(locale)
    palette = {
        "indigo": ("314B9B", "EEF2FF"),
        "emerald": ("087F5B", "E8F7F0"),
        "gold": ("8A6418", "FBF3D7"),
        "slate": ("334155", "F1F5F9"),
        "rose": ("9F3B5B", "FFF0F4"),
    }.get(document.style, ("314B9B", "EEF2FF"))
    dark_fill = PatternFill("solid", fgColor=palette[0])
    light_fill = PatternFill("solid", fgColor=palette[1])
    white_font = Font(color="FFFFFF", bold=True)
    custom_fields = _quote_custom_fields(document)
    column_count = 9 + len(custom_fields)
    last_column = get_column_letter(column_count)

    sheet.merge_cells(f"A1:{last_column}1")
    sheet["A1"] = proforma_text(locale, "title")
    sheet["A1"].font = Font(size=18, bold=True, color=palette[0])
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 32

    def append_metadata(
        left_label: str,
        left_value: object,
        right_label: str,
        right_value: object,
    ) -> None:
        sheet.append([
            left_label,
            _xlsx_value(left_value),
            "",
            "",
            right_label,
            _xlsx_value(right_value),
            "",
            "",
            "",
            *([""] * len(custom_fields)),
        ])
        row_number = sheet.max_row
        sheet.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=4)
        sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=column_count)
        sheet.cell(row_number, 1).font = Font(bold=True, color=palette[0])
        sheet.cell(row_number, 5).font = Font(bold=True, color=palette[0])
        for cell in sheet[row_number]:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    seller_email = _proforma_value(document, "seller_email", "-")
    seller_phone = _proforma_value(document, "seller_phone", "-")
    append_metadata(
        proforma_text(locale, "seller"),
        _proforma_party_value(document, "seller_name", document.tenant_name),
        proforma_text(locale, "invoice_number"),
        _proforma_number(document),
    )
    append_metadata(
        proforma_text(locale, "seller_address"),
        _proforma_value(document, "seller_address", "-"),
        proforma_text(locale, "issue_date"),
        _proforma_value(document, "issue_date", quote.created_at.date()),
    )
    append_metadata(
        quote_text(locale, "email"),
        seller_email,
        quote_text(locale, "phone"),
        seller_phone,
    )
    append_metadata(
        proforma_text(locale, "buyer"),
        _proforma_party_value(document, "buyer_name", quote.customer_company or quote.customer_name),
        proforma_text(locale, "valid_until"),
        quote.valid_until.date(),
    )
    append_metadata(
        quote_text(locale, "contact"),
        _proforma_party_value(document, "buyer_contact", quote.customer_name),
        quote_text(locale, "currency"),
        quote.currency,
    )
    append_metadata(
        proforma_text(locale, "buyer_address"),
        _proforma_value(document, "buyer_address", "-"),
        quote_text(locale, "email"),
        _proforma_party_value(document, "buyer_email", quote.customer_email or "-"),
    )
    for row_number in (3, 5):
        sheet.cell(row_number, 6).number_format = "yyyy-mm-dd"

    append_metadata(proforma_text(locale, "seller") + " · " + quote_text(locale, "contact"), _proforma_value(document, "seller_contact"), proforma_text(locale, "buyer") + " · " + quote_text(locale, "phone"), _proforma_party_value(document, "buyer_phone", quote.customer_phone or ""))
    if _proforma_value(document, "seller_website") or _proforma_value(document, "seller_tax_number"):
        append_metadata(proforma_text(locale, "website"), _proforma_value(document, "seller_website"), proforma_text(locale, "tax_id"), _proforma_value(document, "seller_tax_number"))

    sheet.append([])
    headers = [
        quote_field_label(locale, "serial_number"),
        quote_field_label(locale, "product_image"),
        quote_field_label(locale, "sku_code"),
        quote_field_label(locale, "product_name"),
        quote_field_label(locale, "specification"),
        quote_field_label(locale, "quantity"),
        quote_field_label(locale, "unit_code"),
        quote_field_label(locale, "unit_price"),
        quote_field_label(locale, "line_total"),
        *[str(field.label) for field in custom_fields],
    ]
    sheet.append(headers)
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.fill = dark_fill
        cell.font = white_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[header_row].height = 28

    for item in quote.items:
        sheet.append([
            item.position,
            None,
            _xlsx_text(item.sku_code_snapshot),
            _xlsx_text(item.name_snapshot),
            _xlsx_text(item.specification_snapshot),
            float(item.quantity),
            _xlsx_text(localize_quote_unit(locale, item.unit_code_snapshot)),
            float(item.unit_price_snapshot),
            float(item.line_total),
            *[_quote_custom_value(field, item) for field in custom_fields],
        ])
        row_number = sheet.max_row
        _place_quote_image(
            sheet,
            row_number=row_number,
            column_number=2,
            image_url=item.image_url_snapshot,
            image_loader=image_loader,
        )
        for cell in sheet[row_number]:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.cell(row_number, 6).number_format = "#,##0.######"
        sheet.cell(row_number, 8).number_format = "#,##0.00"
        sheet.cell(row_number, 9).number_format = "#,##0.00"

    freight = _proforma_freight(document)
    total_rows = [
        (proforma_text(locale, "subtotal"), Decimal(quote.total)),
        (proforma_text(locale, "freight"), freight),
        (proforma_text(locale, "grand_total"), Decimal(quote.total) + freight),
    ]
    for label, amount in total_rows:
        sheet.append(["", "", "", "", "", "", "", label, float(amount), *([""] * len(custom_fields))])
        row_number = sheet.max_row
        sheet.cell(row_number, 8).font = Font(bold=True)
        sheet.cell(row_number, 9).font = Font(bold=True)
        sheet.cell(row_number, 9).number_format = f'"{quote.currency}" #,##0.00'
        if label == proforma_text(locale, "grand_total"):
            for cell in sheet[row_number]:
                cell.fill = light_fill

    def append_section(title: str, entries: list[tuple[str, object]]) -> None:
        populated = [(label, value) for label, value in entries if value not in (None, "")]
        if not populated:
            return
        sheet.append([])
        sheet.append([title])
        title_row = sheet.max_row
        sheet.merge_cells(start_row=title_row, start_column=1, end_row=title_row, end_column=column_count)
        sheet.cell(title_row, 1).fill = dark_fill
        sheet.cell(title_row, 1).font = white_font
        for label, value in populated:
            sheet.append([label, _xlsx_value(value)])
            row_number = sheet.max_row
            sheet.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=column_count)
            sheet.cell(row_number, 1).font = Font(bold=True, color=palette[0])
            sheet.cell(row_number, 2).alignment = Alignment(vertical="top", wrap_text=True)

    append_section(proforma_text(locale, "trade_terms"), [
        (proforma_text(locale, "incoterm"), _proforma_value(document, "incoterm")),
        (proforma_text(locale, "payment_terms"), _proforma_value(document, "payment_terms")),
        (proforma_text(locale, "delivery_terms"), _proforma_value(document, "delivery_terms")),
        (proforma_text(locale, "shipment_method"), _proforma_value(document, "shipment_method")),
        (proforma_text(locale, "port_of_loading"), _proforma_value(document, "port_of_loading")),
        (proforma_text(locale, "port_of_destination"), _proforma_value(document, "port_of_destination")),
    ])
    append_section(proforma_text(locale, "bank_details"), [
        (proforma_text(locale, "beneficiary_name"), _proforma_value(document, "beneficiary_name", _proforma_party_value(document, "seller_name", document.tenant_name))),
        (proforma_text(locale, "bank_name"), _proforma_value(document, "bank_name")),
        (proforma_text(locale, "bank_address"), _proforma_value(document, "bank_address")),
        (proforma_text(locale, "bank_account_number"), _proforma_value(document, "bank_account_number")),
        (proforma_text(locale, "swift_code"), _proforma_value(document, "swift_code")),
    ] if any(_proforma_value(document, field) for field in ("beneficiary_name", "bank_name", "bank_address", "bank_account_number", "swift_code")) else [])
    append_section(proforma_text(locale, "remarks"), [
        (proforma_text(locale, "remarks"), _proforma_value(document, "remarks")),
        (quote_text(locale, "notes"), quote.notes or ""),
    ])
    _append_quote_extra_information(sheet, quote)

    widths = (8, 14, 18, 34, 30, 12, 12, 15, 17, *([22] * len(custom_fields)))
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    _apply_xlsx_grid_borders(sheet)
    _configure_default_quote_printing(sheet, header_row=header_row, last_row=sheet.max_row)

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def render_public_quote_draft_xlsx(
    document: PublicQuoteDocument,
    *,
    template_path: Path | None = None,
    image_loader: QuoteImageLoader | None = None,
    document_type: QuoteDocumentType = "quotation",
) -> bytes:
    if document_type == "packing_list":
        from .packing_list_documents import render_packing_list_xlsx

        return render_packing_list_xlsx(document, image_loader=image_loader)
    if document_type == "proforma_invoice":
        return _render_public_proforma_invoice_xlsx(
            document,
            image_loader=image_loader,
        )
    if document.excel_template is not None and template_path is not None:
        return _render_custom_quote_xlsx(
            document,
            template_path=template_path,
            image_loader=image_loader,
        )
    quote = document.quote
    locale = quote_locale(quote.locale)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = quote_text(locale, "sheet_name")[:31]
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.rightToLeft = quote_is_rtl(locale)
    dark_fill = PatternFill("solid", fgColor="172033")
    light_fill = PatternFill("solid", fgColor="EEF2F7")
    white_font = Font(color="FFFFFF", bold=True)

    custom_fields = _quote_custom_fields(document)
    column_count = len(DEFAULT_QUOTE_HEADERS) + len(custom_fields)
    last_column = get_column_letter(column_count)
    sheet.merge_cells(f"A1:{last_column}1")
    sheet["A1"] = quote_text(locale, "document_title")
    sheet["A1"].font = Font(size=18, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.row_dimensions[1].height = 30

    sheet.append(
        [
            quote_text(locale, "merchant"),
            _xlsx_text(document.tenant_name),
            "",
            "",
            quote_text(locale, "quote_number"),
            _xlsx_text(quote.quote_number),
            "",
            "",
            quote_text(locale, "currency"),
            quote.currency,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    sheet.append(
        [
            quote_text(locale, "customer"),
            _xlsx_text(quote.customer_name),
            "",
            "",
            quote_text(locale, "company"),
            _xlsx_text(quote.customer_company),
            "",
            "",
            quote_text(locale, "date"),
            quote.created_at.date(),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    sheet.append(
        [
            quote_text(locale, "email"),
            _xlsx_text(quote.customer_email),
            "",
            "",
            quote_text(locale, "phone"),
            _xlsx_text(quote.customer_phone),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    for row_number in (2, 3, 4):
        sheet.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=4)
        sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=8)
        sheet.merge_cells(start_row=row_number, start_column=10, end_row=row_number, end_column=column_count)
    sheet.cell(row=3, column=10).number_format = "yyyy-mm-dd"
    sheet.append([])
    sheet.append([*list(quote_headers(locale)), *[str(field.label) for field in custom_fields]])
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.fill = dark_fill
        cell.font = white_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[header_row].height = 28

    total_volume = Decimal("0")
    total_gross_weight = Decimal("0")
    has_total_volume = False
    has_total_gross_weight = False
    for item in quote.items:
        logistics = _logistics_values(item)
        sheet.append(
            [
                item.position,
                None,
                _xlsx_text(item.sku_code_snapshot),
                _xlsx_text(item.name_snapshot),
                float(item.quantity),
                _xlsx_text(localize_quote_unit(locale, item.unit_code_snapshot)),
                logistics["packing_quantity"],
                logistics["carton_dimensions"],
                logistics["gross_weight"],
                logistics["carton_volume"],
                float(item.unit_price_snapshot),
                float(item.line_total),
                logistics["total_volume"],
                logistics["total_gross_weight"],
                _xlsx_text(item.description_snapshot),
                _xlsx_text(item.specification_snapshot),
                _xlsx_text(item.category_snapshot),
                _xlsx_text(quote_text(locale, "separator").join(item.tags_snapshot or [])),
                logistics["minimum_order_quantity"],
                logistics["carton_count"],
                *[_quote_custom_value(field, item) for field in custom_fields],
            ]
        )
        row_number = sheet.max_row
        _place_quote_image(
            sheet,
            row_number=row_number,
            column_number=2,
            image_url=item.image_url_snapshot,
            image_loader=image_loader,
        )
        for cell in sheet[row_number]:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        if isinstance(logistics["total_volume"], (int, float)):
            total_volume += Decimal(str(logistics["total_volume"]))
            has_total_volume = True
        if isinstance(logistics["total_gross_weight"], (int, float)):
            total_gross_weight += Decimal(str(logistics["total_gross_weight"]))
            has_total_gross_weight = True
    sheet.append(
        [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            quote_text(locale, "total"),
            float(quote.total),
            float(total_volume) if has_total_volume else None,
            float(total_gross_weight) if has_total_gross_weight else None,
            "",
            "",
            "",
            "",
            "",
            *([""] * len(custom_fields)),
        ]
    )
    total_row = sheet.max_row
    for cell in sheet[total_row]:
        cell.fill = light_fill
        cell.font = Font(bold=True)
    if quote.notes:
        sheet.append([])
        sheet.append([quote_text(locale, "notes"), _xlsx_text(quote.notes)])
        sheet.merge_cells(
            start_row=sheet.max_row,
            start_column=2,
            end_row=sheet.max_row,
            end_column=column_count,
        )

    _append_quote_extra_information(sheet, quote)

    for index, width in enumerate((*DEFAULT_QUOTE_WIDTHS, *([22] * len(custom_fields))), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:{last_column}{max(header_row, total_row - 1)}"
    for row in sheet.iter_rows(min_row=header_row + 1, max_row=total_row):
        row[4].number_format = "#,##0.######"
        row[6].number_format = "#,##0.######"
        for column_index in (8, 9, 10, 11, 12, 13, 18):
            row[column_index].number_format = "#,##0.00####"
    _apply_xlsx_grid_borders(sheet)
    _configure_default_quote_printing(
        sheet,
        header_row=header_row,
        last_row=sheet.max_row,
    )

    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def render_default_quote_template_xlsx() -> bytes:
    """Return a product-region template merchants can map or customize.

    The final quotation header is system-owned and therefore intentionally
    absent from this workbook.  Uploading this file (or a merchant variant)
    only changes the columns and styling of the product-detail table.
    """

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "商品明细模板"
    sheet.sheet_view.showGridLines = False
    dark_fill = PatternFill("solid", fgColor="172033")
    light_fill = PatternFill("solid", fgColor="EEF2F7")
    column_count = len(DEFAULT_QUOTE_HEADERS)
    last_column = get_column_letter(column_count)
    sheet.append(list(DEFAULT_QUOTE_HEADERS))
    header_row = 1
    for cell in sheet[header_row]:
        cell.fill = dark_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[header_row].height = 28
    sheet.append([None] * len(DEFAULT_QUOTE_HEADERS))
    sheet.row_dimensions[sheet.max_row].height = 52
    sheet.append([])
    sheet.append(
        [
            "说明",
            "该模板只决定报价单的商品明细区域；商家、单号、客户、日期和币种等顶部信息由系统统一生成。未映射列会保留为空。",
            *([None] * (column_count - 2)),
        ]
    )
    sheet.merge_cells(
        start_row=sheet.max_row,
        start_column=2,
        end_row=sheet.max_row,
        end_column=column_count,
    )
    for cell in sheet[sheet.max_row]:
        cell.fill = light_fill
    for index, width in enumerate(DEFAULT_QUOTE_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:{last_column}{header_row + 1}"
    _apply_xlsx_grid_borders(sheet)
    _configure_default_quote_printing(
        sheet,
        header_row=header_row,
        last_row=sheet.max_row,
    )
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()
