from __future__ import annotations

import re
from copy import copy
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl import Workbook, load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils.cell import range_boundaries
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.cell_range import CellRange
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..public_catalog_schemas import PublicQuoteDocument


def _pdf_text(value: object | None) -> str:
    return escape(str(value or ""))


def _xlsx_text(value: object | None) -> str:
    """Force untrusted spreadsheet text to remain text, never a formula."""

    text = str(value or "")
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _xlsx_value(value: object | None) -> object:
    return _xlsx_text(value) if isinstance(value, str) else value


def _template_item_value(field: str, document: PublicQuoteDocument, item) -> object:
    quote = document.quote
    values: dict[str, object | None] = {
        "serial_number": item.position,
        "sku_code": item.sku_code_snapshot,
        "product_name": item.name_snapshot,
        "description": item.description_snapshot,
        "specification": item.specification_snapshot,
        "category": item.category_snapshot,
        "tags": "、".join(item.tags_snapshot or []),
        "quantity": float(item.quantity),
        "unit_code": item.unit_code_snapshot,
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
    return {
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


def _render_custom_quote_xlsx(
    document: PublicQuoteDocument,
    *,
    template_path: Path,
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
        item_count = max(1, len(document.quote.items))
        data_start = spec.data_start_row
        data_end = max(data_start, spec.data_end_row)
        old_count = data_end - data_start + 1
        original_merges = [CellRange(str(item)) for item in sheet.merged_cells.ranges]
        for merged in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(merged))

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

        columns_by_key = {column.key: column for column in spec.columns}
        for offset in range(item_count):
            item = document.quote.items[offset] if document.quote.items else None
            row_number = data_start + offset
            for key, column in columns_by_key.items():
                cell = sheet.cell(row_number, column.index)
                field = spec.column_mappings.get(key)
                if field and item is not None:
                    cell.value = _template_item_value(field, document, item)
                    if field in {"unit_price", "line_total"} and cell.number_format == "General":
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
        _replace_placeholders(workbook, document)
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
    finally:
        workbook.close()


def render_public_quote_draft_pdf(document: PublicQuoteDocument) -> bytes:
    quote = document.quote
    buffer = BytesIO()
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except KeyError:
        pass

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DraftChineseTitle",
        parent=styles["Title"],
        fontName="STSong-Light",
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#172033"),
    )
    body_style = ParagraphStyle(
        "DraftChineseBody",
        parent=styles["BodyText"],
        fontName="STSong-Light",
        fontSize=9,
        leading=13,
    )
    right_style = ParagraphStyle("DraftRight", parent=body_style, alignment=TA_RIGHT)
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"报价单 {quote.quote_number}",
    )
    story = [
        Paragraph("报价单 / QUOTATION", title_style),
        Spacer(1, 6 * mm),
    ]
    metadata = [
        [
            Paragraph(f"商家：{_pdf_text(document.tenant_name)}", body_style),
            Paragraph(f"申请编号：{_pdf_text(quote.quote_number)}", right_style),
        ],
        [
            Paragraph(f"客户：{_pdf_text(quote.customer_name)}", body_style),
            Paragraph(f"提交日期：{quote.created_at:%Y-%m-%d}", right_style),
        ],
        [
            Paragraph(f"公司：{_pdf_text(quote.customer_company or '-')}", body_style),
            Paragraph(f"有效期：{quote.valid_until:%Y-%m-%d}", right_style),
        ],
        [
            Paragraph(f"邮箱：{_pdf_text(quote.customer_email or '-')}", body_style),
            Paragraph(f"币种：{_pdf_text(quote.currency)}", right_style),
        ],
    ]
    meta_table = Table(metadata, colWidths=[90 * mm, 72 * mm])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([meta_table, Spacer(1, 7 * mm)])

    rows: list[list[object]] = [["序号", "SKU", "商品", "数量", "单位", "单价", "小计"]]
    for item in quote.items:
        rows.append(
            [
                str(item.position),
                Paragraph(_pdf_text(item.sku_code_snapshot), body_style),
                Paragraph(_pdf_text(item.name_snapshot), body_style),
                f"{item.quantity:f}",
                Paragraph(_pdf_text(item.unit_code_snapshot), body_style),
                f"{item.unit_price_snapshot:,.2f}",
                f"{item.line_total:,.2f}",
            ]
        )
    rows.append(["", "", "", "", "", "合计", f"{quote.currency} {quote.total:,.2f}"])
    table = Table(
        rows,
        repeatRows=1,
        colWidths=[9 * mm, 25 * mm, 52 * mm, 18 * mm, 18 * mm, 23 * mm, 27 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -2), 0.35, colors.HexColor("#CBD3DF")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEF2F7")),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    if quote.notes:
        story.extend(
            [Spacer(1, 7 * mm), Paragraph(f"备注：{_pdf_text(quote.notes)}", body_style)]
        )
    story.extend(
        [
            Spacer(1, 8 * mm),
            Paragraph(
                "商家联系方式："
                f"{_pdf_text(document.contact_email or '-')}  "
                f"{_pdf_text(document.contact_phone or '')}",
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
) -> bytes:
    if document.excel_template is not None and template_path is not None:
        return _render_custom_quote_xlsx(document, template_path=template_path)
    quote = document.quote
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "报价单"
    dark_fill = PatternFill("solid", fgColor="172033")
    light_fill = PatternFill("solid", fgColor="EEF2F7")
    white_font = Font(color="FFFFFF", bold=True)

    sheet.merge_cells("A1:G1")
    sheet["A1"] = "报价单 / QUOTATION"
    sheet["A1"].font = Font(size=18, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")

    sheet.append(
        [
            "商家",
            _xlsx_text(document.tenant_name),
            "报价单号",
            _xlsx_text(quote.quote_number),
            "币种",
            quote.currency,
            "",
        ]
    )
    sheet.append(
        [
            "客户",
            _xlsx_text(quote.customer_name),
            "客户公司",
            _xlsx_text(quote.customer_company),
            "有效期",
            quote.valid_until.date(),
            "",
        ]
    )
    sheet.append(
        [
            "邮箱",
            _xlsx_text(quote.customer_email),
            "电话",
            _xlsx_text(quote.customer_phone),
            "提交日期",
            quote.created_at.date(),
            "",
        ]
    )
    sheet.append([])
    headers = ["序号", "SKU", "商品名称", "数量", "单位", "单价", "小计"]
    sheet.append(headers)
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.fill = dark_fill
        cell.font = white_font
        cell.alignment = Alignment(horizontal="center")

    for item in quote.items:
        sheet.append(
            [
                item.position,
                _xlsx_text(item.sku_code_snapshot),
                _xlsx_text(item.name_snapshot),
                float(item.quantity),
                _xlsx_text(item.unit_code_snapshot),
                float(item.unit_price_snapshot),
                float(item.line_total),
            ]
        )
    sheet.append(["", "", "", "", "", "合计", float(quote.total)])
    total_row = sheet.max_row
    for cell in sheet[total_row]:
        cell.fill = light_fill
        cell.font = Font(bold=True)
    if quote.notes:
        sheet.append([])
        sheet.append(["备注", _xlsx_text(quote.notes)])
        sheet.merge_cells(
            start_row=sheet.max_row,
            start_column=2,
            end_row=sheet.max_row,
            end_column=7,
        )

    widths = [8, 20, 42, 12, 14, 16, 18]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:G{max(header_row, total_row - 1)}"
    for row in sheet.iter_rows(min_row=header_row + 1, max_row=total_row):
        row[5].number_format = "#,##0.00"
        row[6].number_format = "#,##0.00"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
