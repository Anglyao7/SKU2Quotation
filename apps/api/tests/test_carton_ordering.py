from decimal import Decimal

import pytest

from app.domain.errors import ApplicationError
from app.services.carton_ordering import (
    carton_count, packing_quantity, positive_packing_quantity, validate_carton_quantity,
)


@pytest.mark.parametrize("value,expected", [(None, None), ("", None), ("  ", None), (0, None), (-20, None), (True, None), ("NaN", None), ("Infinity", None), ("20.5 x 40 cm", None), ("24.单个含包装重量：0.283kg", None), (20, "20"), ("20.000", "20"), (" ２０ ", "20"), ("1,000", "1000"), ("0.5", "0.5")])
def test_parse_carton_quantity(value, expected):
    assert positive_packing_quantity(value) == (Decimal(expected) if expected else None)


def test_source_snapshot_wins_over_translated_and_later_values():
    options = {"装箱数": "80", "Unités / carton": "40", "_sku2quotation": {"quote_source_option_values": {"装箱数": "20"}}}
    assert packing_quantity(options) == 20
    options["_sku2quotation"]["order_packing_quantity"] = "10"
    assert packing_quantity(options) == 10
    options["_sku2quotation"]["order_packing_quantity"] = None
    assert packing_quantity(options) is None
    for key in ["units_per_carton", "packing_quantity", "装箱数", "一箱个数"]:
        assert packing_quantity({key: "20"}) == 20


def test_only_whole_cartons_with_precise_decimal_arithmetic():
    for quantity in (20, 40, 100):
        validate_carton_quantity(Decimal(quantity), Decimal(20), "CARTON-SKU")
        assert carton_count(Decimal(quantity), Decimal(20)) == quantity // 20
    for quantity in (1, 19, 21, 39):
        with pytest.raises(ApplicationError, match="multiple of 20"):
            validate_carton_quantity(Decimal(quantity), Decimal(20), "CARTON-SKU")
    validate_carton_quantity(Decimal("1.5"), Decimal("0.5"), "WEIGHT-SKU")
    validate_carton_quantity(Decimal(1), None, "PER-PIECE")
