from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
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
    notice_style = ParagraphStyle(
        "DraftNotice",
        parent=body_style,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#8B1E1E"),
        borderColor=colors.HexColor("#E8B4B4"),
        borderWidth=0.6,
        borderPadding=7,
        backColor=colors.HexColor("#FFF4F4"),
    )
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"报价申请草稿 {quote.quote_number}",
    )
    story = [
        Paragraph("报价申请草稿 / DRAFT", title_style),
        Spacer(1, 3 * mm),
        Paragraph("状态：待人工确认 / PENDING CONFIRMATION", notice_style),
        Spacer(1, 2 * mm),
        Paragraph(_pdf_text(quote.disclaimer), notice_style),
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
            Paragraph(f"预估有效期：{quote.valid_until:%Y-%m-%d}", right_style),
        ],
        [
            Paragraph(f"邮箱：{_pdf_text(quote.customer_email or '-')}", body_style),
            Paragraph(f"币种：{_pdf_text(quote.currency)}", right_style),
        ],
    ]
    meta_table = Table(metadata, colWidths=[90 * mm, 72 * mm])
    meta_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([meta_table, Spacer(1, 7 * mm)])

    rows: list[list[object]] = [["序号", "SKU", "商品", "数量", "单位", "预估单价", "预估小计"]]
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
    rows.append(["", "", "", "", "", "预估合计", f"{quote.currency} {quote.total:,.2f}"])
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


def render_public_quote_draft_xlsx(document: PublicQuoteDocument) -> bytes:
    quote = document.quote
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "报价申请草稿"
    dark_fill = PatternFill("solid", fgColor="172033")
    warning_fill = PatternFill("solid", fgColor="FFF0F0")
    light_fill = PatternFill("solid", fgColor="EEF2F7")
    white_font = Font(color="FFFFFF", bold=True)
    warning_font = Font(color="8B1E1E", bold=True)

    sheet.merge_cells("A1:G1")
    sheet["A1"] = "报价申请草稿 / DRAFT — 待人工确认"
    sheet["A1"].font = Font(size=18, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.merge_cells("A2:G2")
    sheet["A2"] = _xlsx_text(quote.disclaimer)
    sheet["A2"].fill = warning_fill
    sheet["A2"].font = warning_font
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[2].height = 42

    sheet.append(
        [
            "商家",
            _xlsx_text(document.tenant_name),
            "申请编号",
            _xlsx_text(quote.quote_number),
            "状态",
            "待人工确认",
            quote.currency,
        ]
    )
    sheet.append(
        [
            "客户",
            _xlsx_text(quote.customer_name),
            "客户公司",
            _xlsx_text(quote.customer_company),
            "预估有效期",
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
    headers = ["序号", "SKU", "商品名称", "数量", "单位", "预估单价", "预估小计"]
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
    sheet.append(["", "", "", "", "", "预估合计", float(quote.total)])
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
