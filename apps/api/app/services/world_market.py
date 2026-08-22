"""Cached world clock and currency-to-CNY reference-rate data.

The dashboard only needs informational market context, not settlement-grade FX
pricing.  Rates come from Frankfurter's public daily reference endpoint and
are exposed as the amount of CNY represented by one unit of each currency
(for example, ``1 USD = 7.2 CNY``).
times come from TimeAPI's IANA timezone endpoint.  Both calls are best-effort:
the local IANA timezone database and the last successful rates are used when a
provider is unavailable, so an external outage cannot make the dashboard fail.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from threading import RLock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ..workspace_schemas import (
    DashboardExchangeRate,
    DashboardMarketSnapshot,
    DashboardWorldTime,
)


logger = logging.getLogger(__name__)

TIME_API_URL = "https://timeapi.io/api/Time/current/zone"
RATES_API_URL = "https://api.frankfurter.dev/v2/rates"
BASE_CURRENCY = "CNY"
RATE_QUOTE_CURRENCIES = ("USD", "EUR", "TRY", "SAR", "AED", "GBP", "JPY", "KRW")


@dataclass(frozen=True)
class MarketLocation:
    key: str
    label: str
    city: str
    country_code: str
    flag: str
    language: str
    timezone: str
    currency: str


LOCATIONS: tuple[MarketLocation, ...] = (
    MarketLocation("china", "中国", "上海", "CN", "🇨🇳", "中文", "Asia/Shanghai", "CNY"),
    MarketLocation("united_states", "美国", "纽约", "US", "🇺🇸", "English", "America/New_York", "USD"),
    MarketLocation("spain", "西班牙", "马德里", "ES", "🇪🇸", "Español", "Europe/Madrid", "EUR"),
    MarketLocation("turkey", "土耳其", "伊斯坦布尔", "TR", "🇹🇷", "Türkçe", "Europe/Istanbul", "TRY"),
    MarketLocation("arab_region", "阿拉伯地区", "利雅得", "SA", "🇸🇦", "العربية", "Asia/Riyadh", "SAR"),
    MarketLocation("united_arab_emirates", "阿联酋", "迪拜", "AE", "🇦🇪", "العربية", "Asia/Dubai", "AED"),
    MarketLocation("united_kingdom", "英国", "伦敦", "GB", "🇬🇧", "English", "Europe/London", "GBP"),
    MarketLocation("japan", "日本", "东京", "JP", "🇯🇵", "日本語", "Asia/Tokyo", "JPY"),
    MarketLocation("south_korea", "韩国", "首尔", "KR", "🇰🇷", "한국어", "Asia/Seoul", "KRW"),
)

_CURRENCY_META: dict[str, tuple[str, str]] = {
    "CNY": ("人民币", "¥"),
    "USD": ("美元", "$"),
    "EUR": ("欧元", "€"),
    "TRY": ("土耳其里拉", "₺"),
    "SAR": ("沙特里亚尔", "﷼"),
    "AED": ("阿联酋迪拉姆", "د.إ"),
    "GBP": ("英镑", "£"),
    "JPY": ("日元", "¥"),
    "KRW": ("韩元", "₩"),
}

_CACHE_LOCK = RLock()
_CACHE: DashboardMarketSnapshot | None = None
_CACHE_AT = 0.0


def _cache_seconds() -> int:
    try:
        configured = int(os.getenv("DASHBOARD_MARKET_CACHE_SECONDS", "900"))
    except ValueError:
        configured = 900
    return max(60, min(configured, 86_400))


def _request_timeout() -> float:
    try:
        configured = float(os.getenv("DASHBOARD_MARKET_REQUEST_TIMEOUT_SECONDS", "2.5"))
    except ValueError:
        configured = 2.5
    return max(0.5, min(configured, 10.0))


def _zone_now(location: MarketLocation, observed_at: datetime) -> datetime:
    try:
        return observed_at.astimezone(ZoneInfo(location.timezone))
    except ZoneInfoNotFoundError:
        return observed_at


def _offset_text(value: datetime) -> str:
    offset = value.utcoffset()
    total_minutes = int(offset.total_seconds() // 60) if offset is not None else 0
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _local_time_fallback(location: MarketLocation, observed_at: datetime) -> DashboardWorldTime:
    local = _zone_now(location, observed_at)
    return DashboardWorldTime(
        key=location.key,
        label=location.label,
        city=location.city,
        country_code=location.country_code,
        flag=location.flag,
        language=location.language,
        timezone=location.timezone,
        currency=location.currency,
        local_time=local.strftime("%Y-%m-%d %H:%M:%S"),
        utc_offset=_offset_text(local),
        is_dst=bool(local.dst()),
        source="system",
    )


def _fetch_world_time(location: MarketLocation, observed_at: datetime) -> DashboardWorldTime:
    fallback = _local_time_fallback(location, observed_at)
    try:
        response = httpx.get(
            TIME_API_URL,
            params={"timeZone": location.timezone},
            timeout=_request_timeout(),
            follow_redirects=True,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return fallback
        time_text = str(payload.get("dateTime") or "").strip()
        local_time = time_text.replace("T", " ").split(".", 1)[0]
        if not local_time:
            local_time = str(payload.get("time") or "").strip()
        if not local_time:
            return fallback
        return fallback.model_copy(
            update={
                "local_time": local_time,
                "is_dst": bool(payload.get("dstActive", fallback.is_dst)),
                "source": "timeapi.io",
            }
        )
    except Exception as exc:  # pragma: no cover - provider/network dependent
        logger.info("World time provider unavailable for %s: %s", location.timezone, type(exc).__name__)
        return fallback


def _parse_rate(value: Any) -> Decimal | None:
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def _fallback_rates(previous: DashboardMarketSnapshot | None) -> list[DashboardExchangeRate]:
    if previous is not None and previous.exchange_rates:
        return [item.model_copy(update={"source": "cached"}) for item in previous.exchange_rates]
    return [
        DashboardExchangeRate(
            currency=BASE_CURRENCY,
            name=_CURRENCY_META[BASE_CURRENCY][0],
            symbol=_CURRENCY_META[BASE_CURRENCY][1],
            rate=Decimal("1"),
            source="fallback",
        )
    ]


def _fetch_exchange_rates(previous: DashboardMarketSnapshot | None) -> tuple[list[DashboardExchangeRate], str | None, str]:
    try:
        response = httpx.get(
            RATES_API_URL,
            params={
                "base": BASE_CURRENCY,
                "quotes": ",".join(RATE_QUOTE_CURRENCIES),
            },
            timeout=_request_timeout(),
            follow_redirects=True,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else []
        rates: dict[str, tuple[Decimal, str | None]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            currency = str(row.get("quote") or "").strip().upper()
            rate = _parse_rate(row.get("rate"))
            if currency in _CURRENCY_META and rate is not None:
                rates[currency] = (rate, str(row.get("date") or "").strip() or None)
        if not rates:
            raise ValueError("exchange provider returned no supported rates")
        rate_date = next((date for _rate, date in rates.values() if date), None)
        values = [
            DashboardExchangeRate(
                currency=BASE_CURRENCY,
                name=_CURRENCY_META[BASE_CURRENCY][0],
                symbol=_CURRENCY_META[BASE_CURRENCY][1],
                rate=Decimal("1"),
                rate_date=rate_date,
                source="Frankfurter",
            )
        ]
        for currency in RATE_QUOTE_CURRENCIES:
            rate_data = rates.get(currency)
            if rate_data is None:
                continue
            cny_per_currency, item_date = rate_data
            name, symbol = _CURRENCY_META[currency]
            values.append(
                DashboardExchangeRate(
                    currency=currency,
                    name=name,
                    symbol=symbol,
                    # Frankfurter returns 1 CNY in the quoted currency. The
                    # console and quote workbench use the inverse convention:
                    # one unit of the quoted currency expressed in CNY.
                    rate=Decimal("1") / cny_per_currency,
                    rate_date=item_date or rate_date,
                    source="Frankfurter",
                )
            )
        return values, rate_date, "Frankfurter"
    except Exception as exc:  # pragma: no cover - provider/network dependent
        logger.info("Exchange-rate provider unavailable: %s", type(exc).__name__)
        fallback = _fallback_rates(previous)
        fallback_date = next((item.rate_date for item in fallback if item.rate_date), None)
        return fallback, fallback_date, "cached" if previous is not None else "fallback"


def _snapshot(observed_at: datetime, previous: DashboardMarketSnapshot | None) -> DashboardMarketSnapshot:
    times: list[DashboardWorldTime] = []
    with ThreadPoolExecutor(max_workers=min(8, len(LOCATIONS))) as executor:
        futures = {
            executor.submit(_fetch_world_time, location, observed_at): location
            for location in LOCATIONS
        }
        rates_future = executor.submit(_fetch_exchange_rates, previous)
        for future in as_completed(futures):
            times.append(future.result())
    order = {location.key: index for index, location in enumerate(LOCATIONS)}
    times.sort(key=lambda item: order.get(item.key, len(order)))
    rates, rate_date, rate_source = rates_future.result()
    time_sources = {item.source for item in times}
    time_source = (
        "timeapi.io"
        if time_sources == {"timeapi.io"}
        else "timeapi.io + system"
        if "timeapi.io" in time_sources
        else "system"
    )
    return DashboardMarketSnapshot(
        observed_at=observed_at,
        world_times=times,
        exchange_rates=rates,
        rate_date=rate_date,
        time_source=time_source,
        rate_source=rate_source,
    )


def get_dashboard_market_snapshot(observed_at: datetime | None = None) -> DashboardMarketSnapshot:
    """Return cached dashboard market context without making it a hard dependency."""

    global _CACHE, _CACHE_AT
    now = observed_at or datetime.now(UTC)
    with _CACHE_LOCK:
        if _CACHE is not None and monotonic() - _CACHE_AT < _cache_seconds():
            return _CACHE
        previous = _CACHE
        try:
            current = _snapshot(now, previous)
        except Exception as exc:  # pragma: no cover - defensive fail-open guard
            logger.warning("Dashboard market snapshot failed: %s", type(exc).__name__)
            current = previous or _snapshot_local_only(now)
        _CACHE = current
        _CACHE_AT = monotonic()
        return current


def _snapshot_local_only(observed_at: datetime) -> DashboardMarketSnapshot:
    return DashboardMarketSnapshot(
        observed_at=observed_at,
        world_times=[_local_time_fallback(location, observed_at) for location in LOCATIONS],
        exchange_rates=_fallback_rates(None),
        time_source="system",
        rate_source="fallback",
    )


def reset_dashboard_market_cache() -> None:
    """Clear the process-local cache in tests or after configuration changes."""

    global _CACHE, _CACHE_AT
    with _CACHE_LOCK:
        _CACHE = None
        _CACHE_AT = 0.0
