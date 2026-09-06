"""Carton purchase rules use source catalog values, never translated labels."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from ..domain.errors import ApplicationError


PACKING_KEYS = (
    "装箱数", "装箱数量", "一箱个数", "装箱量", "每箱数量", "每箱个数",
    "packingquantity", "unitspercarton", "packingqty", "unitscarton", "qtyctn", "pcsctn",
    "unidadescaja", "koliadedi", "العددفيالكرتون", "梱包数", "포장수량",
    "unidadescaixa", "unitéscarton", "تعداددرکارتن",
)


def positive_packing_quantity(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    # Do not extract a number from arbitrary notes or dimensions.
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
        return None
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0 or number > 1_000_000:
        return None
    return number if number == number.quantize(Decimal("0.000001")) else None


def packing_quantity(options: object) -> Decimal | None:
    if not isinstance(options, Mapping):
        return None
    marker = options.get("_sku2quotation")
    if isinstance(marker, Mapping):
        # Freeze the purchase rule with the order, including explicit per-piece.
        if "order_packing_quantity" in marker:
            return positive_packing_quantity(marker["order_packing_quantity"])
        source = marker.get("quote_source_option_values")
        if isinstance(source, Mapping):
            return packing_quantity(source)
    normalized = {
        re.sub(r"[\s\-_/：:()（）]+", "", str(key).casefold()): value
        for key, value in options.items()
    }
    for key in PACKING_KEYS:
        if key in normalized:
            return positive_packing_quantity(normalized[key])
    return None


def carton_count(quantity: Decimal, packing: Decimal | None) -> Decimal | None:
    return quantity / packing if packing else None


def validate_carton_quantity(quantity: Decimal, packing: Decimal | None, sku_code: str) -> None:
    if packing is not None and quantity % packing != 0:
        raise ApplicationError(
            "PUBLIC_QUOTE_CARTON_QUANTITY_REQUIRED",
            f"SKU {sku_code}: quantity must be a multiple of {packing:f} (units per carton).",
        )
