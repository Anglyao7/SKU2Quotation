from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from openpyxl import Workbook, load_workbook
from PIL import Image as PillowImage
from pydantic import ValidationError
from pypdf import PdfReader

from app.domain.errors import ApplicationError
from app.public_catalog_schemas import (
    PublicQuoteDocument,
    PublicQuoteDraftItemResponse,
    PublicQuoteDraftResponse,
    PublicQuoteDraftSettingsUpdate,
    PublicProformaInvoiceSettings,
)
from app.quote_template_schemas import (
    QuoteExcelColumn,
    QuoteExcelTemplateRenderSpec,
    QuoteExcelTemplateUpdateRequest,
)
from app.services.public_quote_documents import (
    DEFAULT_QUOTE_HEADERS,
    render_default_quote_template_xlsx,
    render_public_quote_draft_pdf,
    render_public_quote_draft_xlsx,
)
from app.use_cases import public_catalog as public_catalog_use_cases
from app.public_catalog_schemas import PublicPackingListItem, PublicPackingListSettings
from app.services.packing_lists import default_item, dimensions, number, packing_rows, packing_settings


class _SubscriptionLookupSession:
    def __init__(self, tier: str):
        self.tier = tier

    def get(self, _model, _tenant_id):
        return SimpleNamespace(subscription_tier=self.tier)


def test_extended_quote_documents_require_elite_subscription():
    with pytest.raises(ApplicationError) as error:
        public_catalog_use_cases._require_extended_quote_documents(
            _SubscriptionLookupSession("TRIAL"),
            uuid4(),
        )
    assert error.value.code == "QUOTE_DOCUMENT_TIER_REQUIRED"
    assert error.value.kind == "forbidden"

    public_catalog_use_cases._require_extended_quote_documents(
        _SubscriptionLookupSession("ELITE"),
        uuid4(),
    )


def _image_bytes() -> bytes:
    output = BytesIO()
    PillowImage.new("RGB", (120, 80), color=(45, 27, 105)).save(
        output,
        format="PNG",
    )
    return output.getvalue()


def test_packing_list_uses_order_snapshots_and_preserves_barcode():
    document = _document()
    item = document.quote.items[0]
    item.option_values_snapshot["13位编码"] = "0012345678905"
    settings = packing_settings(document.quote, document.quote.items)
    assert settings.packing_list_number == "PL-20260801-0001"
    assert settings.items[0].barcode == "0012345678905"
    assert settings.items[0].packing_quantity == Decimal("20")
    document.quote.packing_list = settings
    row = packing_rows(document.quote)[0]
    assert row["carton_count"] == 2
    assert row["quantity"] == 40
    assert row["carton_volume"] == Decimal("0.06")
    assert row["total_volume"] == Decimal("0.12")
    assert row["total_gross_weight"] == Decimal("25")


def test_carton_quote_export_keeps_unit_quantity_and_carton_count():
    from app.services.public_quote_documents import _quote_table_value
    document = _document()
    item = document.quote.items[0]
    item.quantity = Decimal("20")
    item.unit_price_snapshot = Decimal("10")
    item.line_total = Decimal("200")
    document.quote.total = Decimal("200")
    document.quote.locale = "en-US"
    assert _quote_table_value("quantity", document, item) == "20"
    assert _quote_table_value("carton_count", document, item) == "1"
    sheet = load_workbook(BytesIO(render_public_quote_draft_xlsx(document)), data_only=True).active
    header_row = next(row for row in sheet if any(cell.value == "Cartons" for cell in row))
    headers = {cell.value: cell.column for cell in header_row}
    data_row = header_row[0].row + 1
    assert sheet.cell(data_row, headers["Quantity"]).value == 20
    assert sheet.cell(data_row, headers["Cartons"]).value == 1
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(render_public_quote_draft_pdf(document))).pages)
    assert "Cartons" in pdf_text
    assert "200.00" in pdf_text


def test_packing_list_partial_carton_retains_actual_order_quantity():
    document = _document()
    document.quote.items[0].quantity = Decimal(100)
    settings = packing_settings(document.quote, document.quote.items)
    settings.items[0].packing_quantity = Decimal(24)
    settings.items[0].last_carton_gross_weight = Decimal(2)
    document.quote.packing_list = settings
    row = packing_rows(document.quote)[0]
    assert row["carton_count"] == 5
    assert row["quantity"] == 100
    assert row["total_volume"] == Decimal("0.30")
    assert row["total_gross_weight"] == Decimal("52")


def test_packing_list_missing_data_stays_unknown():
    document = _document()
    document.quote.items[0].option_values_snapshot = {}
    row = packing_rows(document.quote)[0]
    assert row["quantity"] == 40
    assert all(row[key] is None for key in ("carton_count", "total_volume", "total_gross_weight"))


def test_packing_list_snapshot_round_trip_and_order_changes():
    document = _document()
    item = document.quote.items[0]
    settings = packing_settings(document.quote, document.quote.items)
    settings.items[0].barcode = "0012345678905"
    settings.items[0].gross_weight = Decimal("11.25")
    draft = SimpleNamespace(quotation_number="QT-ROUNDTRIP", created_at=document.quote.created_at, snapshot={"packing_list": settings.model_dump(mode="json")})
    item.quantity = Decimal(60)
    restored = packing_settings(draft, [item])
    document.quote.packing_list = restored
    assert restored.items[0].barcode == "0012345678905"
    assert packing_rows(document.quote)[0]["total_gross_weight"] == Decimal("33.75")
    assert item.option_values_snapshot["毛重"] == "12.5 kg"
    assert packing_settings(draft, []).items == []


@pytest.mark.parametrize("field,value", [("barcode", "123"), ("barcode", "123456789012A"), ("packing_quantity", 0), ("gross_weight", -1), ("carton_count", "1.5"), ("carton_volume", "NaN")])
def test_packing_list_invalid_fields_rejected(field, value):
    with pytest.raises(ValidationError):
        PublicPackingListItem(item_id=uuid4(), **{field: value})


def test_packing_list_duplicate_items_rejected():
    item = PublicPackingListItem(item_id=uuid4())
    with pytest.raises(ValidationError):
        PublicPackingListSettings(packing_list_number="PL-1", issue_date="2026-09-05", items=[item, item])


def test_packing_list_unit_parsing_and_malformed_legacy_metadata():
    assert dimensions("500×400×300mm") == (Decimal(50), Decimal(40), Decimal(30))
    assert dimensions("0.5 * 0.4 * 0.3 m") == (Decimal(50), Decimal(40), Decimal(30))
    assert number("12500 g", "weight") == Decimal("12.5")
    assert number("60000 cm³", "volume") == Decimal("0.06")
    assert number("12 tonnes", "weight") is None
    assert number("12 sqcm", "volume") is None
    assert dimensions("50 × 40") == (None, None, None)
    assert number("24.单个含包装重量0.283kg") is None
    item = _document().quote.items[0]
    item.option_values_snapshot = {"毛重（kg）": "12.5", "13位编码": "not-a-barcode", "装箱数": "NaN"}
    row = default_item(item)
    assert row.gross_weight == Decimal("12.5")
    assert row.barcode == "" and row.packing_quantity is None


def test_packing_list_xlsx_has_exact_columns_images_text_codes_and_totals():
    document = _document()
    document.quote.items[0].option_values_snapshot["13位编码"] = "0012345678905"
    settings = packing_settings(document.quote, document.quote.items)
    settings.items[0].name = "=1+1"
    document.quote.packing_list = settings
    output = render_public_quote_draft_xlsx(document, document_type="packing_list", image_loader=lambda _: _image_bytes())
    sheet = load_workbook(BytesIO(output)).active
    assert sheet.max_column == 12
    assert [cell.value for cell in sheet[5]][:4] == ["图片", "名称", "货号", "13位编码"]
    assert sheet["D6"].value == "0012345678905" and sheet["D6"].data_type == "s"
    assert sheet["B6"].data_type == "s" and sheet["B6"].value == "'=1+1"
    assert sheet["I6"].value == 2 and sheet["J6"].value == 40
    assert sheet["K7"].value == 0.12 and sheet["L7"].value == 25
    assert len(sheet._images) == 1
    assert sheet.freeze_panes == "E6" and sheet.page_setup.orientation == "landscape"
    assert "USD" not in str(list(sheet.values)) and "2.50" not in str(list(sheet.values))


@pytest.mark.parametrize("document_type", ["quotation", "packing_list", "proforma_invoice"])
def test_document_workbench_xlsx_exports_have_visible_borders(document_type):
    document = _document()
    document.quote.locale = "en-US"
    if document_type == "packing_list":
        document.quote.packing_list = packing_settings(document.quote, document.quote.items)

    workbook = load_workbook(
        BytesIO(render_public_quote_draft_xlsx(document, document_type=document_type)),
        data_only=False,
    )
    sheet = workbook.active
    populated_cells = [
        cell
        for row in sheet.iter_rows()
        for cell in row
        if cell.value not in (None, "")
    ]
    assert populated_cells
    assert all(
        cell.border.left.style == "thin"
        and cell.border.right.style == "thin"
        and cell.border.top.style == "thin"
        and cell.border.bottom.style == "thin"
        for cell in populated_cells
    )
    workbook.close()


def test_packing_list_pdf_is_landscape_and_contains_no_prices():
    document = _document()
    document.quote.locale = "en-US"
    document.quote.items[0].name_snapshot = "Pet travel mat"
    output = render_public_quote_draft_pdf(document, document_type="packing_list", image_loader=lambda _: _image_bytes())
    pdf = PdfReader(BytesIO(output))
    page = pdf.pages[0]
    assert page.mediabox.width > page.mediabox.height
    text = page.extract_text()
    assert "PACKING LIST" in text and "PL-20260801-0001" in text
    assert "Pet travel mat" in text and "Cartons" in text
    assert "USD" not in text and "Unit price" not in text


def test_quote_reuses_version_compatible_sku_translation_after_offer_metadata_change() -> None:
    """Changing a tag must not make the translated quote name fall back to Chinese."""

    tenant_id = uuid4()
    sku_id = uuid4()
    product_id = uuid4()
    row = (
        SimpleNamespace(tags=["新品"], display_tag="新品"),
        SimpleNamespace(
            id=sku_id,
            tenant_id=tenant_id,
            product_id=product_id,
            sku_code="SKU-001",
            name="大型犬牵引绳",
            option_values={"规格名称": "白色"},
            version=2,
        ),
        SimpleNamespace(
            id=product_id,
            tenant_id=tenant_id,
            name="大型犬牵引绳",
            description="适用大型犬",
            current_version=3,
        ),
        SimpleNamespace(path="宠物用品/牵引绳", name="牵引绳", code="LEASH"),
    )
    stored = SimpleNamespace(
        source_hash="0" * 64,
        source_category="宠物用品/牵引绳",
        name="Large Dog Leash",
        description="For large dogs",
        category="Pet Supplies/Leashes",
        tags=["Featured"],
        display_tag="Featured",
        product_version=3,
        sku_version=2,
    )

    translated = public_catalog_use_cases._stored_quote_sku_translation(stored, row)

    assert translated is not None
    assert translated.name == "Large Dog Leash"
    assert translated.description == "For large dogs"
    assert translated.category == "Pet Supplies/Leashes"
    # Tags belong to the changed offer metadata and must not be copied from the
    # stale translation row.
    assert translated.tags == ("新品",)
    assert translated.complete is False

    row[1].version = 3
    assert public_catalog_use_cases._stored_quote_sku_translation(stored, row) is None


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
        updated_at=now,
        content_hash="a" * 64,
        proforma_invoice=PublicProformaInvoiceSettings(
            invoice_number="PI-20260801-0001",
            issue_date=now.date(),
            seller_address="No. 18 Export Road, Shanghai",
            seller_email="pi@example.test",
            seller_phone="+86 21 5555 0100",
            buyer_address="100 Market Street, London",
            incoterm="FOB Shanghai",
            payment_terms="30% deposit, 70% before shipment",
            delivery_terms="20 days after deposit",
            shipment_method="Sea freight",
            port_of_loading="Shanghai",
            port_of_destination="Felixstowe",
            beneficiary_name="Example Merchant Limited",
            bank_name="Example International Bank",
            bank_address="1 Finance Road, Shanghai",
            bank_account_number="6222000000000000",
            swift_code="EXAMPLESHXXX",
            freight=Decimal("25.00"),
            remarks="Bank charges are borne by the buyer.",
        ),
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


def test_quote_pdf_embeds_item_thumbnail() -> None:
    content = render_public_quote_draft_pdf(
        _document(),
        image_loader=lambda _url: _image_bytes(),
    )

    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    xobjects = page.get("/Resources", {}).get("/XObject", {})
    assert any(
        obj.get_object().get("/Subtype") == "/Image"
        for obj in xobjects.values()
    )


def test_quote_pdf_settings_limit_visible_columns_to_five() -> None:
    accepted = PublicQuoteDraftSettingsUpdate(
        visible_columns=[
            "product_image",
            "product_name",
            "quantity",
            "unit_price",
            "line_total",
        ],
    )
    assert len(accepted.visible_columns or []) == 5

    with pytest.raises(ValidationError):
        PublicQuoteDraftSettingsUpdate(
            visible_columns=[
                "serial_number",
                "sku_code",
                "product_name",
                "quantity",
                "unit_price",
                "line_total",
            ],
        )


def test_proforma_invoice_pdf_contains_trade_and_banking_details() -> None:
    document = _document()
    document.quote.locale = "en-US"

    content = render_public_quote_draft_pdf(
        document,
        document_type="proforma_invoice",
    )

    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) == 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "PROFORMA INVOICE" in text
    assert "PI-20260801-0001" in text
    assert "示例商家" in text
    assert "带图片的测试商品" in text
    assert "\x00" not in text
    assert "FOB Shanghai" in text
    assert "Example International Bank" in text
    assert "USD 125.00" in text


def test_proforma_invoice_xlsx_is_standalone_and_includes_grand_total() -> None:
    document = _document()
    document.quote.locale = "en-US"

    content = render_public_quote_draft_xlsx(
        document,
        document_type="proforma_invoice",
        image_loader=lambda _url: _image_bytes(),
    )

    workbook = load_workbook(BytesIO(content), data_only=False)
    sheet = workbook["Proforma Invoice"]
    assert sheet["A1"].value == "PROFORMA INVOICE"
    values = [cell.value for row in sheet.iter_rows() for cell in row]
    assert "PI-20260801-0001" in values
    assert "FOB Shanghai" in values
    assert "Example International Bank" in values
    assert 125 in values
    assert len(sheet._images) == 1
    assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)
    workbook.close()


def test_proforma_party_overrides_are_saved_and_exported_without_changing_order() -> None:
    document = _document()
    invoice = document.quote.proforma_invoice
    invoice.seller_name = "Independent Export Co"
    invoice.seller_contact = "Elena"
    invoice.seller_website = "https://export.example.test"
    invoice.seller_tax_number = "0012345678"
    invoice.buyer_name = "Import Trading Co"
    invoice.buyer_contact = "Marco"
    invoice.buyer_email = "pi-buyer@example.test"
    invoice.buyer_phone = "+39 555 1234"
    original_buyer = document.quote.customer_name
    snapshot = SimpleNamespace(created_at=document.quote.created_at, quotation_number="QT-001", snapshot={"proforma_invoice": invoice.model_dump(mode="json")})
    restored = public_catalog_use_cases._draft_proforma_invoice(snapshot)
    assert restored == invoice
    document.quote.proforma_invoice = restored
    pdf = PdfReader(BytesIO(render_public_quote_draft_pdf(document, document_type="proforma_invoice", image_loader=lambda _: _image_bytes())))
    pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert sum(len(page.images) for page in pdf.pages) == 1
    workbook = load_workbook(BytesIO(render_public_quote_draft_xlsx(document, document_type="proforma_invoice")))
    xlsx_text = "\n".join(str(cell.value or "") for row in workbook.active for cell in row)
    for value in (invoice.seller_name, invoice.seller_contact, invoice.seller_website, invoice.seller_tax_number, invoice.buyer_name, invoice.buyer_contact, invoice.buyer_email, invoice.buyer_phone):
        assert value in pdf_text
        assert value in xlsx_text
    assert "USD 125.00" in pdf_text
    assert document.quote.customer_name == original_buyer
    assert document.tenant_name == "示例商家"
    workbook.close()


def test_proforma_explicitly_cleared_buyer_fields_do_not_fall_back_in_exports() -> None:
    document = _document()
    document.quote.proforma_invoice.buyer_name = ""
    document.quote.proforma_invoice.buyer_contact = ""
    document.quote.proforma_invoice.buyer_email = ""
    document.quote.proforma_invoice.buyer_phone = ""
    pdf = PdfReader(BytesIO(render_public_quote_draft_pdf(document, document_type="proforma_invoice")))
    pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    workbook = load_workbook(BytesIO(render_public_quote_draft_xlsx(document, document_type="proforma_invoice")))
    xlsx_text = "\n".join(str(cell.value or "") for row in workbook.active for cell in row)
    for value in (document.quote.customer_name, document.quote.customer_company, document.quote.customer_email, document.quote.customer_phone):
        assert value not in pdf_text
        assert value not in xlsx_text
    workbook.close()


def test_proforma_multi_page_pdf_retains_every_item_and_one_total() -> None:
    document = _document()
    document.quote.locale = "en-US"
    original = document.quote.items[0]
    document.quote.items = [original.model_copy(update={"id": uuid4(), "sku_code_snapshot": f"INVOICE-{index:03}", "position": index}) for index in range(40)]
    document.quote.total = Decimal("4000")
    content = render_public_quote_draft_pdf(document, document_type="proforma_invoice", image_loader=lambda _: _image_bytes())
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) > 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for index in range(40):
        assert f"INVOICE-{index:03}" in text
    assert text.count("USD 4,025.00") == 1
    assert "\x00" not in text


def test_quote_excel_template_only_maps_product_region_fields() -> None:
    accepted = QuoteExcelTemplateUpdateRequest(
        name="商品区域",
        column_mappings={"A": "product_image", "B": "product_name"},
    )
    assert accepted.column_mappings["B"] == "product_name"

    with pytest.raises(ValidationError):
        QuoteExcelTemplateUpdateRequest(
            name="错误的整单模板",
            column_mappings={"A": "quote_number"},
        )


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
    rendered_sheet = rendered["报价单"]
    assert rendered_sheet["A1"].value == "报价单"
    assert rendered_sheet["B2"].value == "示例商家"
    assert rendered_sheet["B8"].value == 20
    assert rendered_sheet["C8"].value is None
    assert rendered_sheet["D8"].value == 0.12
    assert rendered_sheet["E8"].value == 25
    assert len(rendered_sheet._images) == 1
    rendered.close()


def test_downloadable_system_template_exposes_all_default_columns() -> None:
    workbook = load_workbook(
        BytesIO(render_default_quote_template_xlsx()),
        data_only=False,
    )
    sheet = workbook["商品明细模板"]
    header_row = next(
        row
        for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "序号"
    )
    assert tuple(cell.value for cell in sheet[header_row]) == DEFAULT_QUOTE_HEADERS
    assert "保留为空" in str(sheet.cell(header_row + 3, 2).value)
    assert not any(
        cell.value == "商家"
        for row in sheet.iter_rows()
        for cell in row
    )
    assert all(
        cell.data_type != "f"
        for row in sheet.iter_rows()
        for cell in row
    )
    workbook.close()
