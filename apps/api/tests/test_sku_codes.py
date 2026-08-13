from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.services.sku_codes import (
    derive_merchant_sku_prefix,
    format_sku_code,
    merchant_business_date,
)


def test_merchant_prefix_uses_first_four_ascii_characters() -> None:
    assert derive_merchant_sku_prefix("YoYo Trading") == "YOYO"
    assert derive_merchant_sku_prefix("AI") == "AIXX"
    assert derive_merchant_sku_prefix("晴晚", slug="qing-wan") == "QING"
    assert derive_merchant_sku_prefix("晴晚", slug="晴晚") == "SHOP"


def test_managed_sku_code_contains_date_product_and_variant_sequences() -> None:
    assert format_sku_code(
        merchant_prefix="YOYO",
        product_date=date(2026, 8, 13),
        product_sequence=12,
        sku_sequence=3,
    ) == "YOYO-260813012-003"


def test_product_sequence_expands_beyond_three_digits_without_truncation() -> None:
    assert format_sku_code(
        merchant_prefix="YOYO",
        product_date=date(2026, 8, 13),
        product_sequence=1_000,
        sku_sequence=1,
    ) == "YOYO-2608131000-001"


def test_managed_sku_code_rejects_variant_sequence_over_three_digits() -> None:
    with pytest.raises(ValueError, match="between 1 and 999"):
        format_sku_code(
            merchant_prefix="YOYO",
            product_date=date(2026, 8, 13),
            product_sequence=1,
            sku_sequence=1_000,
        )


def test_merchant_business_date_uses_merchant_timezone() -> None:
    tenant = SimpleNamespace(timezone="Asia/Shanghai")
    issued_at = datetime(2026, 8, 12, 16, 30, tzinfo=UTC)
    assert merchant_business_date(tenant, issued_at=issued_at) == date(2026, 8, 13)
