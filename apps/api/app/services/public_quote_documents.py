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
from typing import Callable
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import escape

import httpx
import reportlab
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.worksheet.cell_range import CellRange
from PIL import Image as PillowImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..public_catalog_schemas import PublicQuoteDocument
from .quote_localization import (
    localize_known_quote_template_label,
    localize_quote_unit,
    quote_field_label,
    quote_headers,
    quote_is_rtl,
    quote_label_aliases,
    quote_locale,
    quote_text,
)


QuoteImageLoader = Callable[[str], bytes | None]
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
)

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
    packing = _positive_decimal(packing_raw)
    gross_weight = _gross_weight_kg(gross_raw)
    carton_volume = _carton_volume_m3(volume_raw) or _dimensions_volume_m3(
        dimensions_raw
    )
    quantity = Decimal(str(getattr(item, "quantity", 0) or 0))
    carton_factor = quantity / packing if packing and quantity >= 0 else None
    return {
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
    sheet.print_area = f"A1:N{last_row}"


def _template_item_value(field: str, document: PublicQuoteDocument, item) -> object:
    quote = document.quote
    locale = quote_locale(quote.locale)
    logistics = _logistics_values(item)
    values: dict[str, object | None] = {
        "serial_number": item.position,
        "sku_code": item.sku_code_snapshot,
        "product_name": item.name_snapshot,
        "description": item.description_snapshot,
        "specification": item.specification_snapshot,
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


def _placeholder_values(document: PublicQuoteDocument) -> dict[str, object]:
    quote = document.quote
    values: dict[str, object] = {
        "quote_number": quote.quote_number,
        "报价单号": quote.quote_number,
        "quote_date": quote.created_at.date(),
        "报价日期": quote.created_at.date(),
        "valid_until": quote.valid_until.date(),
        "有效期": quote.valid_until.date(),
        "customer_name": quote.customer_name,
        "客户姓名": quote.customer_name,
        "customer_company": quote.customer_company or "",
        "客户公司": quote.customer_company or "",
        "customer_email": quote.customer_email or "",
        "客户邮箱": quote.customer_email or "",
        "customer_phone": quote.customer_phone or "",
        "客户电话": quote.customer_phone or "",
        "merchant_name": document.tenant_name,
        "商家名称": document.tenant_name,
        "currency": quote.currency,
        "币种": quote.currency,
        "subtotal": float(quote.subtotal),
        "total": float(quote.total),
        "合计": float(quote.total),
        "notes": quote.notes or "",
        "备注": quote.notes or "",
    }
    localized_values = {
        "quote_number": quote.quote_number,
        "quote_date": quote.created_at.date(),
        "valid_until": quote.valid_until.date(),
        "customer": quote.customer_name,
        "company": quote.customer_company or "",
        "email": quote.customer_email or "",
        "phone": quote.customer_phone or "",
        "merchant": document.tenant_name,
        "currency": quote.currency,
        "total": float(quote.total),
        "notes": quote.notes or "",
    }
    for label_key, value in localized_values.items():
        for alias in quote_label_aliases(label_key):
            values.setdefault(alias, value)
    return values


_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_CELL_RANGE_PATTERN = re.compile(
    r"(?P<first_col>\$?[A-Z]{1,3})(?P<first_row>\$?\d+):"
    r"(?P<last_col>\$?[A-Z]{1,3})(?P<last_row>\$?\d+)"
)


def _replace_placeholders(workbook, document: PublicQuoteDocument) -> None:
    values = _placeholder_values(document)
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f" or not isinstance(cell.value, str):
                    continue
                matches = list(_PLACEHOLDER_PATTERN.finditer(cell.value))
                if not matches:
                    continue
                if len(matches) == 1 and matches[0].span() == (0, len(cell.value)):
                    replacement = values.get(matches[0].group(1).strip())
                    if replacement is not None:
                        cell.value = _xlsx_value(replacement)
                    continue
                text = cell.value
                for match in matches:
                    replacement = values.get(match.group(1).strip())
                    if replacement is not None:
                        text = text.replace(match.group(0), str(replacement))
                cell.value = _xlsx_text(text)


def _copy_template_row(sheet, *, source_row: int, target_row: int) -> None:
    source_dimension = sheet.row_dimensions[source_row]
    target_dimension = sheet.row_dimensions[target_row]
    target_dimension.height = source_dimension.height
    target_dimension.hidden = source_dimension.hidden
    target_dimension.outlineLevel = source_dimension.outlineLevel
    for column in range(1, sheet.max_column + 1):
        source = sheet.cell(source_row, column)
        target = sheet.cell(target_row, column)
        if source.data_type == "f" and isinstance(source.value, str):
            try:
                target.value = Translator(
                    source.value,
                    origin=source.coordinate,
                ).translate_formula(target.coordinate)
            except Exception:
                target.value = source.value
        else:
            target.value = source.value
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        target.font = copy(source.font)
        target.fill = copy(source.fill)
        target.border = copy(source.border)
        target.alignment = copy(source.alignment)
        target.protection = copy(source.protection)


def _shifted_merge_ranges(
    ranges: list[CellRange],
    *,
    data_start: int,
    data_end: int,
    item_count: int,
) -> list[str]:
    delta = item_count - (data_end - data_start + 1)
    new_end = data_start + item_count - 1
    result: list[str] = []
    for merged in ranges:
        if merged.max_row < data_start:
            result.append(str(merged))
        elif merged.min_row > data_end:
            shifted = CellRange(str(merged))
            shifted.shift(row_shift=delta)
            result.append(str(shifted))
        elif merged.min_row >= data_start and merged.max_row <= data_end:
            if merged.min_row == merged.max_row == data_start:
                for row_number in range(data_start, new_end + 1):
                    result.append(
                        str(
                            CellRange(
                                min_col=merged.min_col,
                                min_row=row_number,
                                max_col=merged.max_col,
                                max_row=row_number,
                            )
                        )
                    )
        else:
            adjusted = CellRange(str(merged))
            if adjusted.max_row >= data_end:
                adjusted.max_row = max(adjusted.min_row, adjusted.max_row + delta)
            result.append(str(adjusted))
    return result


def _rewrite_data_formula_ranges(
    formula: str,
    *,
    data_start: int,
    data_end: int,
    new_end: int,
) -> str:
    def replace(match: re.Match[str]) -> str:
        first_raw = match.group("first_row")
        last_raw = match.group("last_row")
        first = int(first_raw.replace("$", ""))
        last = int(last_raw.replace("$", ""))
        if data_start <= first <= data_end and data_start <= last <= data_end:
            first = data_start if first == data_start else min(first, new_end)
            last = new_end if last == data_end else min(last, new_end)
            first_prefix = "$" if first_raw.startswith("$") else ""
            last_prefix = "$" if last_raw.startswith("$") else ""
            return (
                f"{match.group('first_col')}{first_prefix}{first}:"
                f"{match.group('last_col')}{last_prefix}{last}"
            )
        return match.group(0)

    return _CELL_RANGE_PATTERN.sub(replace, formula)


def _remove_template_data_images(
    sheet: object,
    *,
    data_start: int,
    data_end: int,
    image_columns: set[int],
) -> None:
    if not image_columns:
        return
    retained = []
    for image in getattr(sheet, "_images", []):
        marker = getattr(getattr(image, "anchor", None), "_from", None)
        if marker is None:
            retained.append(image)
            continue
        row_number = int(marker.row) + 1
        column_number = int(marker.col) + 1
        if data_start <= row_number <= data_end and column_number in image_columns:
            continue
        retained.append(image)
    sheet._images = retained


def _render_custom_quote_xlsx(
    document: PublicQuoteDocument,
    *,
    template_path: Path,
    image_loader: QuoteImageLoader | None,
) -> bytes:
    spec = document.excel_template
    if spec is None:
        raise ValueError("custom quote template configuration is missing")
    workbook = load_workbook(
        template_path,
        data_only=False,
        keep_links=False,
    )
    try:
        if spec.sheet_name not in workbook.sheetnames:
            raise ValueError("configured quote worksheet is missing")
        sheet = workbook[spec.sheet_name]
        sheet.sheet_view.rightToLeft = quote_is_rtl(document.quote.locale)
        item_count = max(1, len(document.quote.items))
        data_start = spec.data_start_row
        data_end = max(data_start, spec.data_end_row)
        old_count = data_end - data_start + 1
        original_merges = [CellRange(str(item)) for item in sheet.merged_cells.ranges]
        columns_by_key = {column.key: column for column in spec.columns}
        image_columns = {
            column.index
            for key, column in columns_by_key.items()
            if spec.column_mappings.get(key) == "product_image"
        }
        _remove_template_data_images(
            sheet,
            data_start=data_start,
            data_end=data_end,
            image_columns=image_columns,
        )
        for merged in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(merged))

        for key, column in columns_by_key.items():
            field = spec.column_mappings.get(key)
            if field:
                sheet.cell(spec.header_row, column.index).value = quote_field_label(
                    document.quote.locale,
                    field,
                )

        if old_count > 1:
            sheet.delete_rows(data_start + 1, old_count - 1)
        if item_count > 1:
            sheet.insert_rows(data_start + 1, item_count - 1)
            for row_number in range(data_start + 1, data_start + item_count):
                _copy_template_row(
                    sheet,
                    source_row=data_start,
                    target_row=row_number,
                )

        for offset in range(item_count):
            item = document.quote.items[offset] if document.quote.items else None
            row_number = data_start + offset
            for key, column in columns_by_key.items():
                cell = sheet.cell(row_number, column.index)
                field = spec.column_mappings.get(key)
                if field == "product_image" and item is not None:
                    cell.value = None
                    _place_quote_image(
                        sheet,
                        row_number=row_number,
                        column_number=column.index,
                        image_url=item.image_url_snapshot,
                        image_loader=image_loader,
                    )
                elif field and item is not None:
                    cell.value = _template_item_value(field, document, item)
                    if field in {
                        "unit_price",
                        "line_total",
                        "gross_weight",
                        "carton_volume",
                        "total_volume",
                        "total_gross_weight",
                    } and cell.number_format == "General":
                        cell.number_format = "#,##0.00"
                elif cell.data_type != "f":
                    cell.value = None

        new_end = data_start + item_count - 1
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f" and isinstance(cell.value, str):
                    cell.value = _rewrite_data_formula_ranges(
                        cell.value,
                        data_start=data_start,
                        data_end=data_end,
                        new_end=new_end,
                    )

        delta = item_count - old_count
        for table in sheet.tables.values():
            min_col, min_row, max_col, max_row = range_boundaries(table.ref)
            if min_row <= data_start <= max_row and max_row >= data_end:
                table.ref = (
                    f"{get_column_letter(min_col)}{min_row}:"
                    f"{get_column_letter(max_col)}{max_row + delta}"
                )
        if sheet.auto_filter.ref:
            min_col, min_row, max_col, max_row = range_boundaries(sheet.auto_filter.ref)
            if min_row <= data_start <= max_row and max_row >= data_end:
                sheet.auto_filter.ref = (
                    f"{get_column_letter(min_col)}{min_row}:"
                    f"{get_column_letter(max_col)}{max_row + delta}"
                )

        for merged in _shifted_merge_ranges(
            original_merges,
            data_start=data_start,
            data_end=data_end,
            item_count=item_count,
        ):
            sheet.merge_cells(merged)
        for row in sheet.iter_rows():
            for cell in row:
                if (
                    data_start <= cell.row <= new_end
                    or cell.data_type == "f"
                    or not isinstance(cell.value, str)
                ):
                    continue
                cell.value = localize_known_quote_template_label(
                    cell.value,
                    document.quote.locale,
                )
        _replace_placeholders(workbook, document)
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
    finally:
        workbook.close()


def _register_quote_pdf_font(locale: str) -> str:
    cid_fonts = {
        "zh-CN": "STSong-Light",
        "ja": "HeiseiMin-W3",
        "ko": "HYSMyeongJo-Medium",
    }
    cid_font = cid_fonts.get(locale)
    if cid_font:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(cid_font))
        except KeyError:
            pass
        return cid_font

    if locale == "ar":
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
    if locale == "ar" and re.search(r"[\u0600-\u06ff]", text):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display

            text = get_display(arabic_reshaper.reshape(text))
        except ImportError:
            # Production installs the shaping helpers. This fallback keeps
            # development downloads functional before dependencies are synced.
            pass
    return escape(text)


_PUBLIC_QUOTE_TABLE_FIELDS = frozenset(
    {
        "serial_number",
        "product_name",
        "description",
        "specification",
        "category",
        "tags",
        "product_image",
        "quantity",
        "unit_code",
        "packing_quantity",
        "carton_dimensions",
        "gross_weight",
        "carton_volume",
        "unit_price",
        "line_total",
        "total_volume",
        "total_gross_weight",
        "currency",
    }
)
_PUBLIC_QUOTE_DEFAULT_FIELDS = (
    "serial_number",
    "product_name",
    "quantity",
    "unit_code",
    "unit_price",
    "line_total",
)
_PUBLIC_QUOTE_COLUMN_WIDTHS_MM = {
    "serial_number": 10,
    "product_name": 42,
    "description": 38,
    "specification": 32,
    "category": 26,
    "tags": 28,
    "product_image": 20,
    "quantity": 18,
    "unit_code": 18,
    "packing_quantity": 22,
    "carton_dimensions": 30,
    "gross_weight": 22,
    "carton_volume": 22,
    "unit_price": 25,
    "line_total": 28,
    "total_volume": 24,
    "total_gross_weight": 26,
    "currency": 18,
}
_PUBLIC_QUOTE_TEXT_LIMITS = {
    "product_name": 120,
    "description": 180,
    "specification": 100,
    "category": 80,
    "tags": 100,
    "carton_dimensions": 80,
}


def _clip_quote_table_text(value: object | None, field: str) -> str:
    text = " ".join(str(value if value is not None else "").split())
    limit = _PUBLIC_QUOTE_TEXT_LIMITS.get(field, 64)
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


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
    # Customer-facing PDFs never expose internal SKU codes or other metadata.
    fields: list[str] = []
    for field in candidates:
        if field not in _PUBLIC_QUOTE_TABLE_FIELDS or field == "sku_code":
            continue
        if field not in fields:
            fields.append(field)
    return fields or list(_PUBLIC_QUOTE_DEFAULT_FIELDS)


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
    return [
        custom_headers.get(field) or quote_field_label(locale, field)
        for field in fields
    ]


def _quote_table_value(field: str, document: PublicQuoteDocument, item: object) -> str:
    value = _template_item_value(field, document, item)
    if value in (None, ""):
        return ""
    if field in {"quantity", "packing_quantity"}:
        try:
            return f"{Decimal(str(value)):f}".rstrip("0").rstrip(".")
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


def render_public_quote_draft_pdf(document: PublicQuoteDocument) -> bytes:
    quote = document.quote
    locale = quote_locale(quote.locale)
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
        title=f"{quote_text(locale, 'document_title')} {quote.quote_number}",
    )
    story = [
        Paragraph(_pdf_localized_text(quote_text(locale, "document_title"), locale), title_style),
        Spacer(1, 6 * mm),
    ]
    metadata = [
        [
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'merchant')}: {document.tenant_name}", locale), body_style),
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'quote_number')}: {quote.quote_number}", locale), right_style),
        ],
        [
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'customer')}: {quote.customer_name}", locale), body_style),
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'submitted_date')}: {quote.created_at:%Y-%m-%d}", locale), right_style),
        ],
        [
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'company')}: {quote.customer_company or '-'}", locale), body_style),
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'valid_until')}: {quote.valid_until:%Y-%m-%d}", locale), right_style),
        ],
        [
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'email')}: {quote.customer_email or '-'}", locale), body_style),
            Paragraph(_pdf_localized_text(f"{quote_text(locale, 'currency')}: {quote.currency}", locale), right_style),
        ],
    ]
    meta_table = Table(metadata, colWidths=[90 * mm, 72 * mm])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([meta_table, Spacer(1, 7 * mm)])

    table_fields = _public_quote_table_fields(document)
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
    table_headers = _public_quote_table_headers(document, table_fields, locale)
    rows: list[list[object]] = [[
        Paragraph(_pdf_localized_text(header, locale), table_header_style)
        for header in table_headers
    ]]
    for item in quote.items:
        rows.append([
            Paragraph(_pdf_localized_text(_quote_table_value(field, document, item), locale), table_body_style)
            for field in table_fields
        ])
    total_row = [""] * len(table_fields)
    total_row[max(0, len(table_fields) - 2)] = Paragraph(
        _pdf_localized_text(quote_text(locale, "total"), locale),
        table_body_style,
    )
    total_row[-1] = Paragraph(
        _pdf_localized_text(f"{quote.currency} {quote.total:,.2f}", locale),
        table_body_style,
    )
    rows.append(total_row)
    numeric_indexes = {
        index for index, field in enumerate(table_fields)
        if field in {
            "quantity",
            "packing_quantity",
            "gross_weight",
            "carton_volume",
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
        colWidths=_quote_table_widths(table_fields),
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette["accent"])),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -2), 0.35, colors.HexColor(palette["border"])),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(palette["soft"])),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                *numeric_commands,
            ]
        )
    )
    story.append(table)
    if quote.notes:
        story.extend(
            [Spacer(1, 7 * mm), Paragraph(_pdf_localized_text(f"{quote_text(locale, 'notes')}: {quote.notes}", locale), body_style)]
        )
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


def render_public_quote_draft_xlsx(
    document: PublicQuoteDocument,
    *,
    template_path: Path | None = None,
    image_loader: QuoteImageLoader | None = None,
) -> bytes:
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

    sheet.merge_cells("A1:N1")
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
            quote_text(locale, "valid_until"),
            quote.valid_until.date(),
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
            quote_text(locale, "submitted_date"),
            quote.created_at.date(),
            "",
            "",
            "",
            "",
        ]
    )
    for row_number in (2, 3, 4):
        sheet.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=4)
        sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=8)
        sheet.merge_cells(start_row=row_number, start_column=10, end_row=row_number, end_column=14)
    sheet.append([])
    sheet.append(list(quote_headers(locale)))
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
            end_column=14,
        )

    for index, width in enumerate(DEFAULT_QUOTE_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:N{max(header_row, total_row - 1)}"
    for row in sheet.iter_rows(min_row=header_row + 1, max_row=total_row):
        row[4].number_format = "#,##0.######"
        row[6].number_format = "#,##0.######"
        for column_index in (8, 9, 10, 11, 12, 13):
            row[column_index].number_format = "#,##0.00####"
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
    """Return the downloadable system template used when no custom template exists."""

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "报价单"
    sheet.sheet_view.showGridLines = False
    dark_fill = PatternFill("solid", fgColor="172033")
    light_fill = PatternFill("solid", fgColor="EEF2F7")
    sheet.merge_cells("A1:N1")
    sheet["A1"] = "报价单 / QUOTATION"
    sheet["A1"].font = Font(size=18, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.row_dimensions[1].height = 30
    sheet.append(
        [
            "商家",
            "{{商家名称}}",
            "",
            "",
            "报价单号",
            "{{报价单号}}",
            "",
            "",
            "币种",
            "{{币种}}",
            "",
            "",
            "",
            "",
        ]
    )
    sheet.append(
        [
            "客户",
            "{{客户姓名}}",
            "",
            "",
            "客户公司",
            "{{客户公司}}",
            "",
            "",
            "有效期",
            "{{有效期}}",
            "",
            "",
            "",
            "",
        ]
    )
    sheet.append(
        [
            "邮箱",
            "{{客户邮箱}}",
            "",
            "",
            "电话",
            "{{客户电话}}",
            "",
            "",
            "报价日期",
            "{{报价日期}}",
            "",
            "",
            "",
            "",
        ]
    )
    for row_number in (2, 3, 4):
        sheet.merge_cells(start_row=row_number, start_column=2, end_row=row_number, end_column=4)
        sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=8)
        sheet.merge_cells(start_row=row_number, start_column=10, end_row=row_number, end_column=14)
    sheet.append([])
    sheet.append(list(DEFAULT_QUOTE_HEADERS))
    header_row = sheet.max_row
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
            "系统无法提供或商家选择不填充的列会保留为空。",
            *([None] * 12),
        ]
    )
    sheet.merge_cells(
        start_row=sheet.max_row,
        start_column=2,
        end_row=sheet.max_row,
        end_column=14,
    )
    for cell in sheet[sheet.max_row]:
        cell.fill = light_fill
    for index, width in enumerate(DEFAULT_QUOTE_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:N{header_row + 1}"
    _configure_default_quote_printing(
        sheet,
        header_row=header_row,
        last_row=sheet.max_row,
    )
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()
