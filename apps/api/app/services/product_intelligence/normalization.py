import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


NORMALIZATION_RULE_VERSION = "product-normalization-v1"

_SPACE_RE = re.compile(r"\s+")
_NUMBER_WITH_UNIT_RE = re.compile(
    r"^\s*([-+]?[0-9]+(?:[.,][0-9]+)?)\s*"
    r"(ml|l|kg|g|mm|cm|m|pcs?|pieces?|units?|件|个)?\s*$",
    re.IGNORECASE,
)
_DIMENSION_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*[x×*]\s*"
    r"([0-9]+(?:\.[0-9]+)?)"
    r"(?:\s*[x×*]\s*([0-9]+(?:\.[0-9]+)?))?\s*"
    r"(mm|cm|m)?\s*$",
    re.IGNORECASE,
)
_PACKING_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*"
    r"(pcs?|pieces?|件|个)\s*(?:/|per\s+)\s*"
    r"(ctns?|cartons?|箱)\s*$",
    re.IGNORECASE,
)
_COLOR_SEPARATOR_RE = re.compile(r"\s*[,;/|、，]\s*")

_PIECE_UNITS = {"pc", "pcs", "piece", "pieces", "unit", "units", "件", "个"}
_MATERIAL_ALIASES = {
    "tpr": "TPR",
    "thermoplastic rubber": "TPR",
    "thermoplastic elastomer": "TPE",
    "tpe": "TPE",
    "polyvinyl chloride": "PVC",
    "pvc": "PVC",
    "silicone": "Silicone",
    "silicon": "Silicone",
    "rubber": "Rubber",
    "abs": "ABS",
    "stainless steel": "Stainless Steel",
}


@dataclass(frozen=True, slots=True)
class NormalizedProductField:
    value: dict[str, Any]
    unit: str | None
    validation_status: str
    warnings: tuple[str, ...]
    trace: tuple[dict[str, Any], ...]
    rule_version: str = NORMALIZATION_RULE_VERSION


def _clean_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _decimal_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _parse_number(value: str) -> Decimal:
    token = value.strip()
    if token.count(",") == 1 and "." not in token:
        left, right = token.split(",", 1)
        token = f"{left}.{right}" if len(right) <= 2 else f"{left}{right}"
    else:
        token = token.replace(",", "")
    return Decimal(token)


def _canonical_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    lowered = unit.casefold()
    if lowered in _PIECE_UNITS:
        return "piece"
    return {"ml": "mL", "l": "L", "kg": "kg", "g": "g", "mm": "mm", "cm": "cm", "m": "m"}.get(
        lowered,
        lowered,
    )


def _quantity(
    text: str,
    *,
    default_unit: str | None = None,
    convert_large_metric: bool = True,
) -> tuple[dict[str, Any], str | None, list[dict[str, Any]]] | None:
    match = _NUMBER_WITH_UNIT_RE.fullmatch(text)
    if match is None:
        return None
    try:
        number = _parse_number(match.group(1))
    except InvalidOperation:
        return None
    unit = _canonical_unit(match.group(2)) or default_unit
    trace: list[dict[str, Any]] = [{"rule": "parse-number-unit", "input": text}]
    if convert_large_metric and unit == "mL" and number >= 1000:
        number /= Decimal(1000)
        unit = "L"
        trace.append({"rule": "millilitre-to-litre", "factor": "0.001"})
    elif convert_large_metric and unit == "g" and number >= 1000:
        number /= Decimal(1000)
        unit = "kg"
        trace.append({"rule": "gram-to-kilogram", "factor": "0.001"})
    payload: dict[str, Any] = {"value": _decimal_text(number)}
    if unit:
        payload["unit"] = unit
    return payload, unit, trace


def normalize_product_field(field_key: str, raw_value: Any) -> NormalizedProductField:
    """Normalize one untrusted field deterministically without inventing business facts."""

    key = field_key.strip().casefold()
    text = _clean_text(raw_value)
    warnings: list[str] = []
    trace: list[dict[str, Any]] = [{"rule": "trim-and-collapse-whitespace"}]
    unit: str | None = None
    value: dict[str, Any] = {"value": text}

    if not text:
        return NormalizedProductField(
            value={"value": ""},
            unit=None,
            validation_status="FAILED",
            warnings=("EMPTY_VALUE",),
            trace=tuple(trace),
        )

    if key == "moq":
        parsed = _quantity(text, default_unit="piece", convert_large_metric=False)
        if parsed is None:
            warnings.append("MOQ_FORMAT_REVIEW_REQUIRED")
        else:
            value, unit, quantity_trace = parsed
            trace.extend(quantity_trace)
            if Decimal(str(value["value"])) < 0:
                warnings.append("MOQ_MUST_BE_NONNEGATIVE")

    elif key in {"weight", "capacity"}:
        parsed = _quantity(text)
        if parsed is None:
            warnings.append("QUANTITY_UNIT_REVIEW_REQUIRED")
        else:
            value, unit, quantity_trace = parsed
            trace.extend(quantity_trace)

    elif key in {"specification", "size", "dimensions"}:
        dimensions = _DIMENSION_RE.fullmatch(text)
        if dimensions is not None:
            values = [dimensions.group(1), dimensions.group(2)]
            if dimensions.group(3) is not None:
                values.append(dimensions.group(3))
            unit = _canonical_unit(dimensions.group(4))
            value = {
                "dimensions": [_decimal_text(Decimal(item)) for item in values],
                "axis_order": "UNCONFIRMED",
            }
            if unit:
                value["unit"] = unit
            warnings.append("DIMENSION_AXIS_ORDER_REVIEW_REQUIRED")
            trace.append({"rule": "parse-dimensions", "axis_count": len(values)})
        else:
            parsed = _quantity(text)
            if parsed is not None:
                value, unit, quantity_trace = parsed
                trace.extend(quantity_trace)

    elif key == "packing":
        packing = _PACKING_RE.fullmatch(text)
        if packing is None:
            warnings.append("PACKING_STRUCTURE_REVIEW_REQUIRED")
        else:
            value = {
                "quantity": _decimal_text(Decimal(packing.group(1))),
                "unit": "piece",
                "level": "carton",
            }
            unit = "piece/carton"
            trace.append({"rule": "parse-pieces-per-carton"})

    elif key == "material":
        canonical = _MATERIAL_ALIASES.get(text.casefold())
        if canonical is None:
            warnings.append("MATERIAL_VOCABULARY_REVIEW_REQUIRED")
        else:
            value = {"value": canonical}
            trace.append({"rule": "platform-material-alias", "canonical": canonical})

    elif key == "color":
        colors = [item for item in _COLOR_SEPARATOR_RE.split(text) if item]
        if len(colors) > 1:
            value = {"values": colors, "variant_relation": "UNCONFIRMED"}
            warnings.append("COLOR_VARIANT_RELATION_REVIEW_REQUIRED")
            trace.append({"rule": "split-color-list", "count": len(colors)})

    elif key == "price":
        warnings.append("PRICE_REQUIRES_SUPPLIER_PRICE_WORKFLOW")

    status = "WARNING" if warnings else "PASS"
    if "MOQ_MUST_BE_NONNEGATIVE" in warnings:
        status = "FAILED"
    return NormalizedProductField(
        value=value,
        unit=unit,
        validation_status=status,
        warnings=tuple(warnings),
        trace=tuple(trace),
    )
