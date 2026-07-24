from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.product_template_import import (
    PRODUCT_TEMPLATE_HEADERS,
    PRODUCT_TEMPLATE_SHEET,
    ProductTemplateValidationError,
    parse_product_template,
)


def _write_workbook(path: Path, rows: list[list[object]], *, headers=None) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = PRODUCT_TEMPLATE_SHEET
    sheet.append(list(headers or PRODUCT_TEMPLATE_HEADERS))
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def test_fixed_template_keeps_note_without_creating_a_moq(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [[
            "柔雾唇釉",
            "唇彩",
            "SKU-001",
            "20",
            "轻盈柔雾质地",
            "12",
            "https://img.example.com/sku-001.jpg",
            *([None] * 9),
        ]],
    )

    result = parse_product_template(path)

    assert len(result.rows) == 1
    assert result.rows[0].sku_code == "SKU-001"
    assert str(result.rows[0].unit_price) == "20.00"
    assert result.rows[0].note == "12"
    assert result.rows[0].default_moq is None
    assert result.rows[0].image_urls == ("https://img.example.com/sku-001.jpg",)
    assert result.warnings == ()


def test_duplicate_sku_is_case_and_whitespace_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            ["商品 A", "分类", " sku-dup ", 10, None, 1, *([None] * 10)],
            ["商品 B", "分类", "SkU-DuP", 12, None, 1, *([None] * 10)],
        ],
    )

    result = parse_product_template(path)

    assert [row.name for row in result.rows] == ["商品 A"]
    assert [row.sku_code for row in result.rows] == ["SKU-DUP"]
    assert result.skipped_rows == 1
    assert "第 3 行" in result.warnings[0]
    assert "第 2 行" in result.warnings[0]


def test_price_is_half_up_quantized_to_two_decimal_places(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            ["商品 A", "分类", "price-a", "12.344", None, None, *([None] * 10)],
            ["商品 B", "分类", "price-b", "12.345", None, None, *([None] * 10)],
        ],
    )

    result = parse_product_template(path)

    assert [row.sku_code for row in result.rows] == ["PRICE-A", "PRICE-B"]
    assert [str(row.unit_price) for row in result.rows] == ["12.34", "12.35"]
    assert result.warnings == ()


def test_price_respects_numeric_20_2_boundary(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            [
                "最大价格",
                "分类",
                "MAX-PRICE",
                "999999999999999999.99",
                None,
                None,
                *([None] * 10),
            ],
            [
                "溢出价格",
                "分类",
                "OVERFLOW-PRICE",
                "999999999999999999.995",
                None,
                None,
                *([None] * 10),
            ],
        ],
    )

    with pytest.raises(ProductTemplateValidationError, match=r"Numeric\(20,2\)"):
        parse_product_template(path)


@pytest.mark.parametrize(
    "row, message",
    [
        (
            ["", "分类", "INVALID-NAME", 10, None, None, *([None] * 10)],
            "缺少商品名称",
        ),
        (
            ["商品", "分类", "INVALID-PRICE", "not-a-price", None, None, *([None] * 10)],
            "商品价格不是有效数字",
        ),
        (
            ["商品", "分类", "INVALID-IMAGE", 10, None, None, "javascript:alert(1)", *([None] * 9)],
            "商品图片1不是有效",
        ),
        (
            ["商品", "分类", "FORMULA", "=1+1", None, None, *([None] * 10)],
            "包含公式",
        ),
    ],
)
def test_invalid_row_rejects_the_full_snapshot(
    tmp_path: Path,
    row: list[object],
    message: str,
) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(path, [row])

    with pytest.raises(ProductTemplateValidationError, match=message):
        parse_product_template(path)


def test_wrong_headers_are_rejected_before_rows_are_read(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    wrong_headers = list(PRODUCT_TEMPLATE_HEADERS)
    wrong_headers[2] = "SKU"
    _write_workbook(path, [], headers=wrong_headers)

    with pytest.raises(ProductTemplateValidationError, match="表头"):
        parse_product_template(path)


def test_current_root_template_matches_contract() -> None:
    template_path = Path(__file__).resolve().parents[3] / "商品模版.xlsx"
    if not template_path.exists():
        pytest.skip("root product template is not present")

    result = parse_product_template(template_path)

    assert len(result.rows) == 600
    assert result.skipped_rows == 8
    assert sum(row.unit_price is None for row in result.rows) == 103
    assert sum("重复" in warning for warning in result.warnings) == 8
