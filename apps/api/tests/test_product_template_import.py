from decimal import Decimal
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
            " 青湾 供应链 ",
            "20",
            "轻盈柔雾质地",
            "12",
            "新品，热卖, 新品",
            "https://img.example.com/sku-001.jpg",
            *([None] * 9),
        ]],
    )

    result = parse_product_template(path)

    assert len(result.rows) == 1
    assert result.rows[0].sku_code == "SKU-001"
    assert result.rows[0].supplier_name == "青湾 供应链"
    assert str(result.rows[0].unit_price) == "20.00"
    assert result.rows[0].note == "12"
    assert result.rows[0].tags == ("新品", "热卖")
    assert result.rows[0].default_moq is None
    assert result.rows[0].image_urls == ("https://img.example.com/sku-001.jpg",)
    assert result.warnings == ()


def test_duplicate_sku_is_case_and_whitespace_insensitive(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            ["商品 A", "分类", " sku-dup ", None, 10, None, 1, None, *([None] * 10)],
            ["商品 B", "分类", "SkU-DuP", None, 12, None, 1, None, *([None] * 10)],
        ],
    )

    result = parse_product_template(path)

    assert [row.name for row in result.rows] == ["商品 A"]
    assert [row.sku_code for row in result.rows] == ["SKU-DUP"]
    assert result.skipped_rows == 1
    assert "第 3 行" in result.warnings[0]
    assert "第 2 行" in result.warnings[0]


def test_category_path_normalizes_two_levels(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [["商品 A", " 办公用品 ／ 纸品 ", "SKU-CATEGORY", None, 10, None, None, None, *([None] * 10)]],
    )

    result = parse_product_template(path)

    assert result.rows[0].category == "办公用品/纸品"


@pytest.mark.parametrize("category", ["办公用品/纸品/A4", "/纸品", "办公用品/"])
def test_category_path_rejects_empty_or_third_level(
    tmp_path: Path, category: str
) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [["商品 A", category, "SKU-BAD-CATEGORY", None, 10, None, None, None, *([None] * 10)]],
    )

    with pytest.raises(ProductTemplateValidationError, match="商品分类|两级"):
        parse_product_template(path)


def test_price_is_half_up_quantized_to_two_decimal_places(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            ["商品 A", "分类", "price-a", None, "12.344", None, None, None, *([None] * 10)],
            ["商品 B", "分类", "price-b", None, "12.345", None, None, None, *([None] * 10)],
        ],
    )

    result = parse_product_template(path)

    assert [row.sku_code for row in result.rows] == ["PRICE-A", "PRICE-B"]
    assert [str(row.unit_price) for row in result.rows] == ["12.34", "12.35"]
    assert result.warnings == ()


def test_optional_columns_can_be_blank_and_blank_price_defaults_to_zero(
    tmp_path: Path,
) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [[
            "无选填信息商品",
            "基础分类",
            "OPTIONAL-BLANK",
            None,
            None,
            None,
            None,
            None,
            *([None] * 10),
        ]],
    )

    result = parse_product_template(path)

    assert len(result.rows) == 1
    assert result.rows[0].supplier_name is None
    assert result.rows[0].unit_price == Decimal("0.00")
    assert result.rows[0].description is None
    assert result.rows[0].note is None
    assert result.rows[0].tags == ()
    assert result.rows[0].image_urls == ()


def test_blank_category_defaults_to_uncategorized(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [[
            "待分类商品",
            None,
            "UNCATEGORIZED-001",
            None,
            None,
            None,
            None,
            None,
            *([None] * 10),
        ]],
    )

    result = parse_product_template(path)

    assert len(result.rows) == 1
    assert result.rows[0].category == "未分类"
    assert result.rows[0].unit_price == Decimal("0.00")


def test_blank_model_generates_a_stable_temporary_sku(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            [
                "无型号商品",
                "基础分类",
                None,
                "测试供应商",
                "10",
                "第一件",
                None,
                None,
                *([None] * 10),
            ],
            [
                "无型号商品",
                "基础分类",
                None,
                "测试供应商",
                "20",
                "第二件",
                None,
                None,
                *([None] * 10),
            ],
        ],
    )

    first = parse_product_template(path)
    repeated = parse_product_template(path)

    assert len(first.rows) == 2
    assert first.rows[0].sku_code.startswith("AUTO-")
    assert first.rows[1].sku_code == f"{first.rows[0].sku_code}-2"
    assert [row.sku_code for row in repeated.rows] == [
        row.sku_code for row in first.rows
    ]
    assert first.skipped_rows == 0
    assert first.warnings == (
        "有 2 行未填写商品型号，系统已根据商品名称、分类和供应商生成临时型号。",
    )


def test_parser_reports_determinate_row_progress(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            [
                f"进度商品 {index}",
                "进度分类",
                f"PROGRESS-{index:03d}",
                None,
                None,
                None,
                None,
                None,
                *([None] * 10),
            ]
            for index in range(1, 251)
        ],
    )
    progress: list[tuple[int, int]] = []

    result = parse_product_template(
        path,
        progress_callback=lambda processed, total: progress.append((processed, total)),
    )

    assert len(result.rows) == 250
    assert progress[0] == (1, 250)
    assert progress[-1] == (250, 250)
    assert all(total == 250 for _, total in progress)
    assert [processed for processed, _ in progress] == sorted(
        processed for processed, _ in progress
    )


def test_price_respects_numeric_20_2_boundary(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            [
                "最大价格",
                "分类",
                "MAX-PRICE",
                None,
                "999999999999999999.99",
                None,
                None,
                None,
                *([None] * 10),
            ],
            [
                "溢出价格",
                "分类",
                "OVERFLOW-PRICE",
                None,
                "999999999999999999.995",
                None,
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
            ["", "分类", "INVALID-NAME", None, 10, None, None, None, *([None] * 10)],
            "缺少商品名称",
        ),
        (
            ["商品", "分类", "INVALID-PRICE", None, "not-a-price", None, None, None, *([None] * 10)],
            "商品价格不是有效数字",
        ),
        (
            ["商品", "分类", "INVALID-IMAGE", None, 10, None, None, None, "javascript:alert(1)", *([None] * 9)],
            "商品图片1不是有效",
        ),
        (
            ["商品", "分类", "FORMULA", None, "=1+1", None, None, None, *([None] * 10)],
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


def test_validation_collects_complete_row_and_field_details(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    _write_workbook(
        path,
        [
            [
                "",
                "分类",
                "INVALID-MULTI-A",
                None,
                "not-a-price",
                None,
                None,
                None,
                "javascript:alert(1)",
                *([None] * 9),
            ],
            [
                "商品 B",
                "一级/二级/三级",
                "INVALID-MULTI-B",
                None,
                None,
                None,
                None,
                "x" * 81,
                *([None] * 10),
            ],
        ],
    )

    with pytest.raises(ProductTemplateValidationError) as captured:
        parse_product_template(path)

    issues = captured.value.issues
    assert len(issues) == 5
    assert {issue.row_number for issue in issues} == {2, 3}
    assert {
        (issue.row_number, issue.column, issue.code)
        for issue in issues
    } == {
        (2, "商品名称", "REQUIRED_VALUE_MISSING"),
        (2, "商品价格", "PRICE_INVALID"),
        (2, "商品图片1", "IMAGE_URL_INVALID"),
        (3, "商品分类", "CATEGORY_INVALID"),
        (3, "标签", "TAGS_INVALID"),
    }
    assert all(issue.suggestion for issue in issues)
    assert "发现 5 个数据问题" in str(captured.value)


def test_wrong_headers_are_rejected_before_rows_are_read(tmp_path: Path) -> None:
    path = tmp_path / "商品模版.xlsx"
    wrong_headers = list(PRODUCT_TEMPLATE_HEADERS)
    wrong_headers[2] = "SKU"
    _write_workbook(path, [], headers=wrong_headers)

    with pytest.raises(ProductTemplateValidationError, match="表头") as captured:
        parse_product_template(path)

    assert captured.value.issues[0].row_number == 1
    assert captured.value.issues[0].column == "商品型号"
    assert captured.value.issues[0].code == "HEADER_MISMATCH"


def test_current_root_template_matches_contract() -> None:
    template_path = Path(__file__).resolve().parents[3] / "商品模版.xlsx"
    if not template_path.exists():
        pytest.skip("root product template is not present")

    result = parse_product_template(template_path)

    assert len(result.rows) == 600
    assert result.skipped_rows == 8
    assert sum(row.unit_price == Decimal("0.00") for row in result.rows) == 103
    assert len(result.warnings) == 8
    assert sum("重复" in warning for warning in result.warnings) == 8
