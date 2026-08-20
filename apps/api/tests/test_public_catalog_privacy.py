from __future__ import annotations

from app.services.public_catalog_privacy import (
    public_sku_option_values,
    public_specification,
)


def test_public_sku_option_values_removes_internal_note_and_nested_fallback() -> None:
    values = {
        "颜色": "红",
        "备注": "仅后台可见",
        "_sku2quotation": {
            "variant_option_keys": ["颜色", "备注"],
            "quote_source_option_values": {
                "颜色": "红",
                "备注": "仍然不能公开",
            },
        },
    }

    public = public_sku_option_values(values)

    assert public["颜色"] == "红"
    assert "备注" not in public
    assert public["_sku2quotation"]["variant_option_keys"] == ["颜色"]
    assert "备注" not in public["_sku2quotation"]["quote_source_option_values"]


def test_public_specification_removes_note_segments_from_old_quotes() -> None:
    assert public_specification("颜色: 红；备注: 仅后台可见；尺寸: M") == "颜色: 红；尺寸: M"
    assert public_specification("备注：仅后台可见") is None
    assert public_specification("颜色: 红") == "颜色: 红"
