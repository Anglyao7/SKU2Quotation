from decimal import Decimal, ROUND_HALF_UP

from ..models import PriceCalculationRequest, PriceCalculationResponse


CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_price(request: PriceCalculationRequest) -> PriceCalculationResponse:
    additional_cost = sum((item.amount_per_unit for item in request.cost_items), Decimal("0"))
    unit_cost = request.purchase_price + additional_cost
    suggested_unit_price = money(unit_cost / (Decimal("1") - request.target_margin_rate))
    total_cost = money(unit_cost * request.quantity)
    quotation_total = money(suggested_unit_price * request.quantity)
    gross_profit = money(quotation_total - total_cost)
    gross_margin_rate = (gross_profit / quotation_total).quantize(Decimal("0.0001"))
    return PriceCalculationResponse(
        currency=request.currency.upper(),
        quantity=request.quantity,
        purchase_price=money(request.purchase_price),
        unit_cost=money(unit_cost),
        suggested_unit_price=suggested_unit_price,
        total_cost=total_cost,
        quotation_total=quotation_total,
        gross_profit=gross_profit,
        gross_margin_rate=gross_margin_rate,
        formula="suggested_unit_price = unit_cost / (1 - target_margin_rate)",
    )

