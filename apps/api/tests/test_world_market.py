from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services import world_market
from app.use_cases import public_catalog
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


def test_rate_only_snapshot_is_cached_without_fetching_world_times(monkeypatch) -> None:
    calls = 0

    def fake_rates(_previous):
        nonlocal calls
        calls += 1
        return (
            [
                world_market.DashboardExchangeRate(
                    currency="USD",
                    name="美元",
                    symbol="$",
                    rate=Decimal("7.1"),
                    rate_date="2026-08-26",
                )
            ],
            "2026-08-26",
            "Frankfurter",
        )

    monkeypatch.setattr(world_market, "_fetch_exchange_rates", fake_rates)
    monkeypatch.setattr(
        world_market,
        "_fetch_world_time",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("world clocks must not be fetched")
        ),
    )
    world_market.reset_dashboard_market_cache()
    observed_at = datetime(2026, 8, 26, 8, 30, tzinfo=UTC)

    first = world_market.get_exchange_rate_snapshot(observed_at)
    second = world_market.get_exchange_rate_snapshot(observed_at)

    assert calls == 1
    assert first is second
    assert first.world_times == []
    assert first.observed_at == observed_at
    assert first.exchange_rates[0].rate == Decimal("7.1")


def test_public_exchange_rate_response_converts_internal_models(monkeypatch) -> None:
    observed_at = datetime(2026, 8, 26, 8, 30, tzinfo=UTC)
    market = world_market.DashboardMarketSnapshot(
        observed_at=observed_at,
        exchange_rates=[
            world_market.DashboardExchangeRate(
                currency="USD",
                name="美元",
                symbol="$",
                rate=Decimal("7.1"),
                rate_date="2026-08-26",
            )
        ],
        rate_date="2026-08-26",
    )
    monkeypatch.setattr(public_catalog, "_resolve_store", lambda *_args, **_kwargs: (None, None))
    monkeypatch.setattr(public_catalog, "get_exchange_rate_snapshot", lambda: market)

    response = public_catalog.get_public_exchange_rates(object(), slug="demo")

    assert response.observed_at == observed_at
    assert response.exchange_rates[0].currency == "USD"
    assert response.exchange_rates[0].rate == Decimal("7.1")


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
