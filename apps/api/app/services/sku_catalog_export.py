from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..product_center_models import SKU_TEMPLATE_SOURCE_OPTION_KEY
from ..product_supplier_models import ProductImageRow
from ..repositories.product_center_repository import SkuListRow
from .product_template_import import (
    MAX_PRODUCT_IMAGE_COLUMN_COUNT,
    PRODUCT_MASTER_TEMPLATE_HEADERS,
    PRODUCT_MASTER_TEMPLATE_SHEET,
    SKU_DETAIL_TEMPLATE_HEADERS,
    SKU_DETAIL_TEMPLATE_SHEET,
)


def _category_name(row: SkuListRow) -> str:
    category = row.category
    if category is None:
        return "未分类"
    path = str(category.path or "").strip()
    if path and path.casefold() != category.code.casefold():
        return path
    return category.name


def _option_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, Mapping):
        return "；".join(
            f"{key}: {item}"
            for key, item in value.items()
            if item not in (None, "", [], {})
        )
    return str(value).strip()


def _variant_options(values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return the concrete option selected by one SKU in template order."""

    marker = values.get(SKU_TEMPLATE_SOURCE_OPTION_KEY)
    keys: list[str] = []
    if isinstance(marker, Mapping):
        keys = [
            key
            for key in marker.get("variant_option_keys", [])
            if isinstance(key, str) and key.strip()
        ]
    if not keys:
        reserved = {
            SKU_TEMPLATE_SOURCE_OPTION_KEY,
            "商品型号",
            "规格名称",
            "备注",
            "一箱个数",
            "装箱数",
            "毛重",
            "起定数",
            "是否是新品",
        }
        keys = [
            str(key)
            for key, value in values.items()
            if str(key) not in reserved and value not in (None, "", [], {})
        ]
    options = [
        (key, _option_text(values.get(key)))
        for key in keys
        if _option_text(values.get(key))
    ]
    if not options:
        legacy_specification = _option_text(values.get("规格名称"))
        if legacy_specification:
            options.append(("规格", legacy_specification))
    return options[:3]


def _units_per_carton(values: Mapping[str, Any]) -> Any:
    for key in ("装箱数", "一箱个数", "packing_quantity", "units_per_carton"):
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _product_tags(rows: Sequence[SkuListRow], product_id: UUID) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.product.id != product_id or row.public_offer is None:
            continue
        for tag in row.public_offer.tags or []:
            normalized = str(tag).strip()
            if normalized and normalized.casefold() not in seen:
                seen.add(normalized.casefold())
                tags.append(normalized)
    return "，".join(tags)


def _product_default_price(rows: Sequence[SkuListRow], product_id: UUID) -> float:
    prices = [
        float(row.public_offer.unit_price)
        for row in rows
        if row.product.id == product_id
        and row.public_offer is not None
        and row.public_offer.unit_price is not None
    ]
    return min(prices) if prices else 0


def _product_model(rows: Sequence[SkuListRow], product_id: UUID) -> str:
    for row in rows:
        if row.product.id != product_id:
            continue
        value = _option_text(row.sku.option_values.get("商品型号"))
        if value:
            return value
    return ""


def _source_sku_identity(sku: Any) -> str:
    return str(sku.source_sku_code or sku.sku_code or "").strip()


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
    product_sheet.title = PRODUCT_MASTER_TEMPLATE_SHEET
    sku_sheet = workbook.create_sheet(SKU_DETAIL_TEMPLATE_SHEET)
    product_sheet.append(list(PRODUCT_MASTER_TEMPLATE_HEADERS))
    sku_sheet.append(list(SKU_DETAIL_TEMPLATE_HEADERS))

    _style_sheet(
        product_sheet,
        headers=PRODUCT_MASTER_TEMPLATE_HEADERS,
        widths=(
            18,
            28,
            22,
            20,
            14,
            44,
            28,
            26,
            *([38] * MAX_PRODUCT_IMAGE_COLUMN_COUNT),
        ),
    )
    _style_sheet(
        sku_sheet,
        headers=SKU_DETAIL_TEMPLATE_HEADERS,
        widths=(
            18,
            22,
            30,
            18,
            *([16] * 5),
            18,
            *([16] * 5),
            18,
            *([16] * 5),
            18,
            16,
            16,
            16,
            16,
        ),
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
                product.product_code or "",
                product.name,
                _category_name(row),
                _product_model(rows, product.id),
                _product_default_price(rows, product.id),
                product.description or "",
                "",
                _product_tags(rows, product.id),
                *urls,
                *("" for _ in range(MAX_PRODUCT_IMAGE_COLUMN_COUNT - len(urls))),
            ]
        )
        for offset, url in enumerate(urls, start=9):
            cell = product_sheet.cell(row=row_number, column=offset)
            if url.startswith(("https://", "http://")):
                cell.hyperlink = url
                cell.style = "Hyperlink"

    for row in rows:
        sku = row.sku
        offer = row.public_offer
        options = _variant_options(sku.option_values)
        option_cells: list[str] = []
        for option_index in range(3):
            if option_index < len(options):
                name, value = options[option_index]
                option_cells.extend([name, value, "", "", "", ""])
            else:
                option_cells.extend(["", "", "", "", "", ""])
        sku_sheet.append(
            [
                row.product.product_code or "",
                _source_sku_identity(sku),
                sku.name or row.product.name,
                *option_cells,
                supplier_names.get(sku.supplier_id or "", ""),
                float(offer.unit_price) if offer is not None else 0,
                float(sku.weight) if sku.weight is not None else None,
                float(sku.default_moq) if sku.default_moq is not None else None,
                _units_per_carton(sku.option_values),
            ]
        )

    if product_sheet.max_row >= 2:
        product_sheet.auto_filter.ref = f"A1:{get_column_letter(len(PRODUCT_MASTER_TEMPLATE_HEADERS))}{product_sheet.max_row}"
        for cell in product_sheet["E"][1:]:
            cell.number_format = "0.00"
        for row in product_sheet.iter_rows(min_row=2, max_col=len(PRODUCT_MASTER_TEMPLATE_HEADERS)):
            for cell in row:
                cell.alignment = Alignment(
                    vertical="center",
                    wrap_text=cell.column in {2, 3, 6, 7, 8},
                )

    if sku_sheet.max_row >= 2:
        sku_sheet.auto_filter.ref = f"A1:{get_column_letter(len(SKU_DETAIL_TEMPLATE_HEADERS))}{sku_sheet.max_row}"
        for cell in sku_sheet["W"][1:]:
            cell.number_format = "0.00"
        for column in ("X", "Y", "Z"):
            for cell in sku_sheet[column][1:]:
                cell.number_format = "0.######"
        for row in sku_sheet.iter_rows(min_row=2, max_col=len(SKU_DETAIL_TEMPLATE_HEADERS)):
            for cell in row:
                cell.alignment = Alignment(
                    vertical="center",
                    wrap_text=cell.column in {3, 4, 10, 16, 22},
                )

    workbook.calculation.fullCalcOnLoad = True
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
