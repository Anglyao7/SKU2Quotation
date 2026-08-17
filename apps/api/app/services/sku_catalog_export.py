from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from io import BytesIO
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..product_center_models import SKU_TEMPLATE_SOURCE_OPTION_KEY
from ..product_supplier_models import ProductImageRow
from ..repositories.product_center_repository import SkuListRow
from .product_template_import import MAX_PRODUCT_IMAGE_COLUMN_COUNT


PRODUCT_HEADERS = (
    "商品ID",
    "商品编码",
    "商品名称",
    "商品分类",
    "商品描述",
    "默认单位",
    "状态",
    *(f"图片地址{index}" for index in range(1, MAX_PRODUCT_IMAGE_COLUMN_COUNT + 1)),
    "更新时间",
)

SKU_HEADERS = (
    "SKU ID",
    "商品ID",
    "商品编码",
    "SKU编号",
    "来源SKU编号",
    "SKU名称",
    "规格",
    "条码",
    "供应商",
    "公开价",
    "币种",
    "标签",
    "起定数",
    "起定单位",
    "毛重",
    "重量单位",
    "装箱数",
    "状态",
    "源文件",
    "导入时间",
    "更新时间",
)


def _excel_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _category_name(row: SkuListRow) -> str:
    category = row.category
    if category is None:
        return "未分类"
    path = str(category.path or "").strip()
    if path and path.casefold() != category.code.casefold():
        return path
    return category.name


def _display_option_values(values: Mapping[str, Any]) -> str:
    visible: list[str] = []
    for key, value in values.items():
        if key == SKU_TEMPLATE_SOURCE_OPTION_KEY or value in (None, "", [], {}):
            continue
        visible.append(f"{key}: {value}")
    return "；".join(visible)


def _units_per_carton(values: Mapping[str, Any]) -> Any:
    for key in ("装箱数", "一箱个数", "packing_quantity", "units_per_carton"):
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _style_sheet(sheet: object, *, headers: Sequence[str], widths: Sequence[int]) -> None:
    header_fill = PatternFill(fill_type="solid", fgColor="2D1B69")
    header_font = Font(name="Microsoft YaHei", size=10, bold=True, color="FFFFFF")
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 90


def build_sku_catalog_workbook(
    *,
    rows: Sequence[SkuListRow],
    images_by_product: Mapping[UUID, Sequence[ProductImageRow]],
    image_urls: Mapping[UUID, str],
    supplier_names: Mapping[str, str],
) -> bytes:
    """Build a tenant catalog export with stable links and public object URLs."""

    workbook = Workbook()
    product_sheet = workbook.active
    product_sheet.title = "商品"
    sku_sheet = workbook.create_sheet("SKU")
    product_sheet.append(list(PRODUCT_HEADERS))
    sku_sheet.append(list(SKU_HEADERS))

    _style_sheet(
        product_sheet,
        headers=PRODUCT_HEADERS,
        widths=(
            38,
            18,
            30,
            24,
            46,
            12,
            12,
            *([34] * MAX_PRODUCT_IMAGE_COLUMN_COUNT),
            20,
        ),
    )
    _style_sheet(
        sku_sheet,
        headers=SKU_HEADERS,
        widths=(38, 38, 18, 24, 22, 30, 42, 20, 24, 14, 10, 28, 12, 12, 12, 12, 12, 12, 28, 20, 20),
    )
    product_sheet.sheet_properties.tabColor = "D4AF37"
    sku_sheet.sheet_properties.tabColor = "42A58B"
    sku_sheet.freeze_panes = "D2"

    product_rows: dict[UUID, SkuListRow] = {}
    for row in rows:
        product_rows.setdefault(row.product.id, row)

    for row_number, row in enumerate(product_rows.values(), start=2):
        product = row.product
        images = list(images_by_product.get(product.id, ()))[:MAX_PRODUCT_IMAGE_COLUMN_COUNT]
        urls = [image_urls.get(image.id, "") for image in images]
        product_sheet.append(
            [
                str(product.id),
                product.product_code or "",
                product.name,
                _category_name(row),
                product.description or "",
                product.default_unit or "",
                product.status,
                *urls,
                *("" for _ in range(MAX_PRODUCT_IMAGE_COLUMN_COUNT - len(urls))),
                _excel_datetime(product.updated_at),
            ]
        )
        for offset, url in enumerate(urls, start=8):
            cell = product_sheet.cell(row=row_number, column=offset)
            if url.startswith(("https://", "http://")):
                cell.hyperlink = url
                cell.style = "Hyperlink"

    for row in rows:
        sku = row.sku
        offer = row.public_offer
        sku_sheet.append(
            [
                str(sku.id),
                str(row.product.id),
                row.product.product_code or "",
                sku.sku_code,
                sku.source_sku_code or "",
                sku.name or row.product.name,
                _display_option_values(sku.option_values),
                sku.barcode or "",
                supplier_names.get(sku.supplier_id or "", ""),
                float(offer.unit_price) if offer is not None else 0,
                offer.currency if offer is not None else "",
                "，".join(offer.tags) if offer is not None else "",
                float(sku.default_moq) if sku.default_moq is not None else None,
                sku.moq_unit or "",
                float(sku.weight) if sku.weight is not None else None,
                sku.weight_unit or "",
                _units_per_carton(sku.option_values),
                sku.status,
                row.source_filename or "",
                _excel_datetime(row.source_imported_at),
                _excel_datetime(sku.updated_at),
            ]
        )

    if product_sheet.max_row >= 2:
        product_sheet.auto_filter.ref = f"A1:{get_column_letter(len(PRODUCT_HEADERS))}{product_sheet.max_row}"
        product_sheet.column_dimensions["A"].hidden = True
        for cell in product_sheet["R"][1:]:
            cell.number_format = "yyyy-mm-dd hh:mm"
            cell.alignment = Alignment(vertical="center")
        for row in product_sheet.iter_rows(min_row=2, max_col=len(PRODUCT_HEADERS)):
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=cell.column in {3, 4, 5})

    if sku_sheet.max_row >= 2:
        sku_sheet.auto_filter.ref = f"A1:{get_column_letter(len(SKU_HEADERS))}{sku_sheet.max_row}"
        sku_sheet.column_dimensions["A"].hidden = True
        sku_sheet.column_dimensions["B"].hidden = True
        for cell in sku_sheet["J"][1:]:
            cell.number_format = "0.00"
        for column in ("M", "O", "Q"):
            for cell in sku_sheet[column][1:]:
                cell.number_format = "0.######"
        for column in ("T", "U"):
            for cell in sku_sheet[column][1:]:
                cell.number_format = "yyyy-mm-dd hh:mm"
        for row in sku_sheet.iter_rows(min_row=2, max_col=len(SKU_HEADERS)):
            for cell in row:
                cell.alignment = Alignment(vertical="center", wrap_text=cell.column in {6, 7, 12})

    workbook.calculation.fullCalcOnLoad = True
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
