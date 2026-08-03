from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook, load_workbook
from PIL import Image as PillowImage

from app.public_catalog_schemas import (
    PublicQuoteDocument,
    PublicQuoteDraftItemResponse,
    PublicQuoteDraftResponse,
)
from app.quote_template_schemas import (
    QuoteExcelColumn,
    QuoteExcelTemplateRenderSpec,
)
from app.services.public_quote_documents import (
    DEFAULT_QUOTE_HEADERS,
    render_default_quote_template_xlsx,
    render_public_quote_draft_xlsx,
)


def _image_bytes() -> bytes:
    output = BytesIO()
    PillowImage.new("RGB", (120, 80), color=(45, 27, 105)).save(
        output,
        format="PNG",
    )
    return output.getvalue()


def _document(
    *,
    template: QuoteExcelTemplateRenderSpec | None = None,
) -> PublicQuoteDocument:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    item = PublicQuoteDraftItemResponse(
        id=uuid4(),
        sku_id=uuid4(),
        position=1,
        quantity=Decimal("40"),
        sku_code_snapshot="SKU-IMAGE-001",
        name_snapshot="带图片的测试商品",
        description_snapshot="用于验证默认和自定义报价模板。",
        specification_snapshot="紫色 / 大号",
        option_values_snapshot={
            "一箱个数": "20",
            "装箱尺寸": "50 × 40 × 30 cm",
            "毛重": "12.5 kg",
            "立方": "0.06 m³",
        },
        category_snapshot="测试分类",
        tags_snapshot=["图片", "物流"],
        image_url_snapshot="memory://product.png",
        unit_code_snapshot="件",
        currency_snapshot="USD",
        unit_price_snapshot=Decimal("2.50"),
        line_total=Decimal("100.00"),
        product_version=2,
        sku_version=3,
    )
    quote = PublicQuoteDraftResponse(
        id=uuid4(),
        tenant_id=uuid4(),
        quote_number="QD-20260801-0001",
        status="PENDING_CONFIRMATION",
        customer_name="Example Buyer",
        customer_company="Example Company",
        customer_email="buyer@example.test",
        customer_phone="+1 555 0100",
        notes="测试备注",
        currency="USD",
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        total_amount=Decimal("100.00"),
        valid_until=now + timedelta(days=7),
        created_at=now,
        content_hash="a" * 64,
        items=[item],
    )
    return PublicQuoteDocument(
        tenant_name="示例商家",
        contact_email="sales@example.test",
        contact_phone="+86 10000",
        quote=quote,
        excel_template=template,
    )


def test_default_quote_xlsx_embeds_image_and_calculates_logistics_totals() -> None:
    content = render_public_quote_draft_xlsx(
        _document(),
        image_loader=lambda _url: _image_bytes(),
    )

    workbook = load_workbook(BytesIO(content), data_only=False)
    sheet = workbook["报价单"]
    header_row = next(
        row
        for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "序号"
    )
    assert tuple(cell.value for cell in sheet[header_row]) == DEFAULT_QUOTE_HEADERS
    item_row = header_row + 1
    total_row = item_row + 1
    assert sheet.cell(item_row, 3).value == "SKU-IMAGE-001"
    assert sheet.cell(item_row, 7).value == 20
    assert sheet.cell(item_row, 8).value == "50 × 40 × 30 cm"
    assert sheet.cell(item_row, 9).value == 12.5
    assert sheet.cell(item_row, 10).value == 0.06
    assert sheet.cell(item_row, 12).value == 100
    assert sheet.cell(item_row, 13).value == 0.12
    assert sheet.cell(item_row, 14).value == 25
    assert sheet.cell(total_row, 12).value == 100
    assert sheet.cell(total_row, 13).value == 0.12
    assert sheet.cell(total_row, 14).value == 25
    assert len(sheet._images) == 1
    assert all(
        cell.data_type != "f"
        for row in sheet.iter_rows()
        for cell in row
    )
    workbook.close()


def test_custom_quote_xlsx_can_embed_image_and_leave_unmapped_column_blank(
    tmp_path,
) -> None:
    template_path = tmp_path / "custom-quote.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "客户模板"
    headers = ["图片", "装箱数量", "客户自定义列", "总立方", "总毛重"]
    sheet.append(headers)
    sheet.append([None, "示例", "这段示例数据应被清空", None, None])
    workbook.save(template_path)
    workbook.close()

    columns = [
        QuoteExcelColumn(
            key=chr(64 + index),
            index=index,
            header=header,
            samples=[],
        )
        for index, header in enumerate(headers, start=1)
    ]
    spec = QuoteExcelTemplateRenderSpec(
        object_key="quotes/custom-quote.xlsx",
        sheet_name="客户模板",
        header_row=1,
        data_start_row=2,
        data_end_row=2,
        columns=columns,
        column_mappings={
            "A": "product_image",
            "B": "packing_quantity",
            "D": "total_volume",
            "E": "total_gross_weight",
        },
    )
    content = render_public_quote_draft_xlsx(
        _document(template=spec),
        template_path=template_path,
        image_loader=lambda _url: _image_bytes(),
    )

    rendered = load_workbook(BytesIO(content), data_only=False)
    rendered_sheet = rendered["客户模板"]
    assert rendered_sheet["B2"].value == 20
    assert rendered_sheet["C2"].value is None
    assert rendered_sheet["D2"].value == 0.12
    assert rendered_sheet["E2"].value == 25
    assert len(rendered_sheet._images) == 1
    rendered.close()


def test_downloadable_system_template_exposes_all_default_columns() -> None:
    workbook = load_workbook(
        BytesIO(render_default_quote_template_xlsx()),
        data_only=False,
    )
    sheet = workbook["报价单"]
    header_row = next(
        row
        for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "序号"
    )
    assert tuple(cell.value for cell in sheet[header_row]) == DEFAULT_QUOTE_HEADERS
    assert "保留为空" in str(sheet.cell(header_row + 3, 2).value)
    assert all(
        cell.data_type != "f"
        for row in sheet.iter_rows()
        for cell in row
    )
    workbook.close()
