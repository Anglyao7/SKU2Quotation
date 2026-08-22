from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services import world_market
from app.use_cases.public_catalog import _currency_conversion_factor


def test_exchange_rates_are_exposed_as_currency_to_cny(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, str]]:
            return [
                {"quote": "USD", "rate": "0.14", "date": "2026-08-22"},
                {"quote": "EUR", "rate": "0.12", "date": "2026-08-22"},
            ]

    monkeypatch.setattr(world_market.httpx, "get", lambda *_args, **_kwargs: Response())
    rates, rate_date, source = world_market._fetch_exchange_rates(None)

    by_currency = {item.currency: item.rate for item in rates}
    assert by_currency["CNY"] == Decimal("1")
    assert by_currency["USD"] == Decimal("1") / Decimal("0.14")
    assert by_currency["EUR"] == Decimal("1") / Decimal("0.12")
    assert rate_date == "2026-08-22"
    assert source == "Frankfurter"


def test_quote_conversion_uses_currency_to_cny_rates() -> None:
    market = SimpleNamespace(
        exchange_rates=[
            SimpleNamespace(currency="USD", rate=Decimal("7.142857142857")),
            SimpleNamespace(currency="EUR", rate=Decimal("8.333333333333")),
        ]
    )

    assert _currency_conversion_factor(
        market,
        source_currency="CNY",
        target_currency="USD",
    ) == Decimal("1") / Decimal("7.142857142857")
    assert _currency_conversion_factor(
        market,
        source_currency="USD",
        target_currency="CNY",
    ) == Decimal("7.142857142857")
    assert _currency_conversion_factor(
        market,
        source_currency="EUR",
        target_currency="USD",
    ) == Decimal("8.333333333333") / Decimal("7.142857142857")
