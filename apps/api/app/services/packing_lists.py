"""Packing-list defaults and totals, derived from the ordered SKU snapshot."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from ..public_catalog_schemas import PublicPackingListItem, PublicPackingListSettings
from .carton_ordering import packing_quantity

ALIASES = {
    "packing_quantity": ("装箱数量", "装箱数", "装箱量", "一箱个数", "每箱数量", "每箱个数", "qtyctn", "pcsctn", "packingquantity"),
    "dimensions": ("装箱尺寸", "外箱尺寸", "纸箱尺寸", "箱规", "cartonsize", "cartondimensions"),
    "gross_weight": ("毛重", "毛重kg", "箱毛重", "整箱毛重", "grossweight", "grossweightkg", "gw", "gwkg"),
    "carton_volume": ("立方", "立方m³", "立方m3", "单箱立方", "箱体积", "cbm", "cartonvolume"),
    "barcode": ("13位编码", "13位条码", "条形码", "条码", "商品条码", "barcode", "ean13", "ean", "gtin13"),
    "article_number": ("货号", "商品货号", "articlenumber", "itemnumber"),
}


def normalized_key(value: object) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(value)).casefold())


def option(item: object, field: str) -> object | None:
    values = getattr(item, "option_values_snapshot", None) or {}
    marker = values.get("_sku2quotation")
    originals = marker.get("quote_source_option_values") if isinstance(marker, dict) else None
    if isinstance(originals, dict):
        values = {**values, **originals}
    lookup = {normalized_key(k): v for k, v in values.items() if not str(k).startswith("_")}
    for alias in ALIASES[field]:
        value = lookup.get(normalized_key(alias))
        if value not in (None, "", [], {}):
            return value
    return None


def number(value: object, kind: str = "") -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z³0-9/\u3400-\u9fff]*)", text)
    if not match:
        return None
    try:
        result = Decimal(match[1])
        if not result.is_finite() or result <= 0:
            return None
        unit = match[2]
        if kind == "weight":
            if unit not in ("", "kg", "千克", "公斤", "g", "克", "lb", "lbs", "磅"):
                return None
            if unit in ("g", "克"):
                result /= 1000
            elif unit in ("lb", "lbs", "磅"):
                result *= Decimal("0.45359237")
        if kind == "volume":
            if unit not in ("", "m3", "m³", "cbm", "立方米", "立方", "cm3", "cm³", "立方厘米", "dm3", "dm³", "l", "升"):
                return None
            if unit in ("cm3", "cm³", "立方厘米"):
                result /= 1_000_000
            elif unit in ("dm3", "dm³", "l", "升"):
                result /= 1000
        if not kind and unit not in ("", "pcs", "pc", "件", "个", "套", "只", "支", "双", "包", "条"):
            return None
        return result
    except InvalidOperation:
        return None


def dimensions(value: object) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(cm|mm|m|厘米|毫米|米)?\s*", text)
    if not match:
        return None, None, None
    factor = Decimal("0.1") if match[4] in ("mm", "毫米") else Decimal("100") if match[4] in ("m", "米") else Decimal(1)
    result = tuple(Decimal(match[i]) * factor for i in (1, 2, 3))
    return result if all(value > 0 for value in result) else (None, None, None)


def default_item(item: object) -> PublicPackingListItem:
    length, width, height = dimensions(option(item, "dimensions"))
    raw_barcode = str(option(item, "barcode") or "").strip()
    data = dict(item_id=item.id, barcode=raw_barcode if re.fullmatch(r"[0-9]{13}", raw_barcode) else "", article_number=str(option(item, "article_number") or item.sku_code_snapshot), packing_quantity=packing_quantity(getattr(item, "option_values_snapshot", {})), carton_length=length, carton_width=width, carton_height=height, carton_volume=number(option(item, "carton_volume"), "volume"), gross_weight=number(option(item, "gross_weight"), "weight"))
    # Imported metadata is not necessarily a valid editable decimal. Keep
    # valid fields without letting one malformed legacy value break a quote.
    valid = {"item_id": item.id}
    for key, value in data.items():
        try:
            PublicPackingListItem.model_validate({**valid, key: value})
            valid[key] = value
        except ValueError:
            continue
    return PublicPackingListItem.model_validate(valid)


def packing_settings(draft: object, items: list[object]) -> PublicPackingListSettings:
    quote_number = str(getattr(draft, "quotation_number", None) or getattr(draft, "request_number", None) or getattr(draft, "quote_number", ""))
    list_number = "PL-" + re.sub(r"^(?:QD|QT)-", "", quote_number, flags=re.I)
    created = getattr(draft, "created_at", None)
    snapshot = getattr(draft, "snapshot", None) or {}
    raw = snapshot.get("packing_list", {}) if isinstance(snapshot, dict) else {}
    defaults = {"packing_list_number": list_number[:80], "issue_date": created.date() if isinstance(created, datetime) else datetime.now().date()}
    try:
        settings = PublicPackingListSettings.model_validate({**defaults, **raw})
    except (ValueError, TypeError):
        settings = PublicPackingListSettings.model_validate(defaults)
    saved = {row.item_id: row for row in settings.items}
    settings.items = [saved.get(item.id) or default_item(item) for item in items]
    return settings


def packing_rows(quote: object) -> list[dict[str, object]]:
    settings = getattr(quote, "packing_list", None) or packing_settings(quote, quote.items)
    overrides = {row.item_id: row for row in settings.items}
    result = []
    for item in quote.items:
        row = overrides.get(item.id) or default_item(item)
        quantity = Decimal(str(item.quantity))
        volume = row.carton_length * row.carton_width * row.carton_height / 1_000_000 if all(v is not None for v in (row.carton_length, row.carton_width, row.carton_height)) else row.carton_volume
        cartons = row.carton_count if row.carton_count is not None else int((quantity / row.packing_quantity).to_integral_value(rounding=ROUND_CEILING)) if row.packing_quantity else None
        gross = row.gross_weight * cartons if row.gross_weight is not None and cartons is not None else None
        if gross is not None and row.last_carton_gross_weight is not None:
            gross = row.gross_weight * (cartons - 1) + row.last_carton_gross_weight
        result.append({"item_id": item.id, "image_url": item.image_url_snapshot, "name": row.name or item.name_snapshot, "article_number": row.article_number if row.article_number is not None else item.sku_code_snapshot, "barcode": row.barcode or "", "packing_quantity": row.packing_quantity, "carton_dimensions": " × ".join(format(v.normalize(), "f") for v in (row.carton_length, row.carton_width, row.carton_height)) if all(v is not None for v in (row.carton_length, row.carton_width, row.carton_height)) else "", "carton_volume": volume, "gross_weight": row.gross_weight, "carton_count": cartons, "quantity": quantity, "total_volume": volume * cartons if volume is not None and cartons is not None else None, "total_gross_weight": gross})
    return result
