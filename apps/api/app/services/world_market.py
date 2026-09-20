"""Cached world clock and currency-to-CNY reference-rate data.

The dashboard only needs informational market context, not settlement-grade FX
pricing.  Rates come from Frankfurter's public daily reference endpoint and
are exposed as the amount of CNY represented by one unit of each currency
(for example, ``1 USD = 7.2 CNY``).
World clocks use one representative IANA region for each UTC offset and the
local tzdata database, so a third-party clock API cannot make the dashboard
slow or leave different cards out of sync.
"""

from __future__ import annotations

import logging
import os
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
    DashboardTimezoneOption,
    DashboardWorldTime,
)


logger = logging.getLogger(__name__)

RATES_API_URL = "https://api.frankfurter.dev/v2/rates"
BASE_CURRENCY = "CNY"
RATE_QUOTE_CURRENCIES = (
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "KRW",
    "HKD",
    "SGD",
    "AUD",
    "CAD",
    "CHF",
    "NZD",
    "TRY",
    "SAR",
    "AED",
    "INR",
    "THB",
    "MYR",
    "IDR",
    "PHP",
    "MXN",
    "BRL",
    "ZAR",
)


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


# One representative IANA zone is kept for each currently used UTC offset.
# The offset is the user-facing identity; the IANA zone remains the value used
# by Python/JavaScript for correct calendar and daylight-saving calculations.
LOCATIONS: tuple[MarketLocation, ...] = (
    MarketLocation("utc_minus_12", "UTC-12:00", "Etc/GMT+12", "UM", "🌐", "—", "Etc/GMT+12", "USD"),
    MarketLocation("utc_minus_11", "UTC-11:00", "Pacific/Pago_Pago", "AS", "🇦🇸", "English", "Pacific/Pago_Pago", "USD"),
    MarketLocation("utc_minus_10", "UTC-10:00", "Pacific/Honolulu", "US", "🇺🇸", "English", "Pacific/Honolulu", "USD"),
    MarketLocation("utc_minus_9", "UTC-09:00", "Pacific/Gambier", "PF", "🇵🇫", "Français", "Pacific/Gambier", "EUR"),
    MarketLocation("utc_minus_8", "UTC-08:00", "Pacific/Pitcairn", "PN", "🇵🇳", "English", "Pacific/Pitcairn", "USD"),
    MarketLocation("utc_minus_7", "UTC-07:00", "America/Phoenix", "US", "🇺🇸", "English", "America/Phoenix", "USD"),
    MarketLocation("utc_minus_6", "UTC-06:00", "America/Guatemala", "GT", "🇬🇹", "Español", "America/Guatemala", "USD"),
    MarketLocation("utc_minus_5", "UTC-05:00", "America/Bogota", "CO", "🇨🇴", "Español", "America/Bogota", "USD"),
    MarketLocation("utc_minus_4", "UTC-04:00", "America/La_Paz", "BO", "🇧🇴", "Español", "America/La_Paz", "USD"),
    MarketLocation("utc_minus_3", "UTC-03:00", "America/Argentina/Buenos_Aires", "AR", "🇦🇷", "Español", "America/Argentina/Buenos_Aires", "USD"),
    MarketLocation("utc_minus_2", "UTC-02:00", "Atlantic/South_Georgia", "GS", "🇬🇸", "English", "Atlantic/South_Georgia", "GBP"),
    MarketLocation("utc_minus_1", "UTC-01:00", "Atlantic/Cape_Verde", "CV", "🇨🇻", "Português", "Atlantic/Cape_Verde", "EUR"),
    MarketLocation("utc_plus_0", "UTC+00:00", "Africa/Accra", "GH", "🇬🇭", "English", "Africa/Accra", "GHS"),
    MarketLocation("utc_plus_1", "UTC+01:00", "Africa/Lagos", "NG", "🇳🇬", "English", "Africa/Lagos", "USD"),
    MarketLocation("utc_plus_2", "UTC+02:00", "Africa/Johannesburg", "ZA", "🇿🇦", "English", "Africa/Johannesburg", "USD"),
    MarketLocation("utc_plus_3", "UTC+03:00", "Asia/Riyadh", "SA", "🇸🇦", "العربية", "Asia/Riyadh", "SAR"),
    MarketLocation("utc_plus_4", "UTC+04:00", "Asia/Dubai", "AE", "🇦🇪", "العربية", "Asia/Dubai", "AED"),
    MarketLocation("utc_plus_5", "UTC+05:00", "Asia/Karachi", "PK", "🇵🇰", "English", "Asia/Karachi", "USD"),
    MarketLocation("utc_plus_5_30", "UTC+05:30", "Asia/Kolkata", "IN", "🇮🇳", "English", "Asia/Kolkata", "INR"),
    MarketLocation("utc_plus_5_45", "UTC+05:45", "Asia/Kathmandu", "NP", "🇳🇵", "English", "Asia/Kathmandu", "USD"),
    MarketLocation("utc_plus_6", "UTC+06:00", "Asia/Dhaka", "BD", "🇧🇩", "English", "Asia/Dhaka", "USD"),
    MarketLocation("utc_plus_6_30", "UTC+06:30", "Asia/Yangon", "MM", "🇲🇲", "မြန်မာ", "Asia/Yangon", "USD"),
    MarketLocation("utc_plus_7", "UTC+07:00", "Asia/Bangkok", "TH", "🇹🇭", "ไทย", "Asia/Bangkok", "THB"),
    MarketLocation("utc_plus_8", "UTC+08:00", "Asia/Shanghai", "CN", "🇨🇳", "中文", "Asia/Shanghai", "CNY"),
    MarketLocation("utc_plus_9", "UTC+09:00", "Asia/Tokyo", "JP", "🇯🇵", "日本語", "Asia/Tokyo", "JPY"),
    MarketLocation("utc_plus_9_30", "UTC+09:30", "Australia/Darwin", "AU", "🇦🇺", "English", "Australia/Darwin", "AUD"),
    MarketLocation("utc_plus_10", "UTC+10:00", "Australia/Brisbane", "AU", "🇦🇺", "English", "Australia/Brisbane", "AUD"),
    MarketLocation("utc_plus_11", "UTC+11:00", "Pacific/Noumea", "NC", "🇳🇨", "Français", "Pacific/Noumea", "EUR"),
    MarketLocation("utc_plus_12", "UTC+12:00", "Pacific/Funafuti", "TV", "🇹🇻", "English", "Pacific/Funafuti", "USD"),
    MarketLocation("utc_plus_13", "UTC+13:00", "Pacific/Tongatapu", "TO", "🇹🇴", "English", "Pacific/Tongatapu", "USD"),
    MarketLocation("utc_plus_14", "UTC+14:00", "Pacific/Kiritimati", "KI", "🇰🇮", "English", "Pacific/Kiritimati", "USD"),
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
    "HKD": ("港币", "HK$"),
    "SGD": ("新加坡元", "S$"),
    "AUD": ("澳元", "A$"),
    "CAD": ("加拿大元", "C$"),
    "CHF": ("瑞士法郎", "CHF"),
    "NZD": ("新西兰元", "NZ$"),
    "INR": ("印度卢比", "₹"),
    "THB": ("泰铢", "฿"),
    "MYR": ("马来西亚林吉特", "RM"),
    "IDR": ("印尼盾", "Rp"),
    "PHP": ("菲律宾比索", "₱"),
    "MXN": ("墨西哥比索", "MX$"),
    "BRL": ("巴西雷亚尔", "R$"),
    "ZAR": ("南非兰特", "R"),
}

DEFAULT_LOCATION_KEYS: tuple[str, ...] = (
    "utc_plus_8",
    "utc_minus_5",
    "utc_plus_0",
    "utc_plus_1",
    "utc_plus_3",
    "utc_plus_4",
    "utc_plus_9",
)
_LOCATION_BY_KEY = {location.key: location for location in LOCATIONS}
_LOCATION_KEY_ALIASES = {
    "china": "utc_plus_8",
    "united_states": "utc_minus_5",
    "spain": "utc_plus_1",
    "turkey": "utc_plus_3",
    "arab_region": "utc_plus_3",
    "united_arab_emirates": "utc_plus_4",
    "united_kingdom": "utc_plus_0",
    "japan": "utc_plus_9",
    "south_korea": "utc_plus_9",
}
_LOCATION_KEY_BY_TIMEZONE = {location.timezone: location.key for location in LOCATIONS}

_CACHE_LOCK = RLock()
_CACHE: dict[tuple[str, ...], DashboardMarketSnapshot] = {}
_CACHE_AT: dict[tuple[str, ...], float] = {}
_RATE_CACHE: DashboardMarketSnapshot | None = None
_RATE_CACHE_AT = 0.0


def normalize_location_keys(value: object | None) -> tuple[str, ...]:
    """Return configured location keys in the canonical market order.

    ``None`` means the legacy/default dashboard set. An explicitly empty list
    is preserved so an owner can temporarily hide every clock and add them
    back later from the dashboard controls.
    """

    if value is None:
        return DEFAULT_LOCATION_KEYS
    if not isinstance(value, (list, tuple, set, frozenset)):
        return DEFAULT_LOCATION_KEYS
    selected = {
        _LOCATION_KEY_ALIASES.get(str(item).strip(), _LOCATION_KEY_BY_TIMEZONE.get(str(item).strip(), str(item).strip()))
        for item in value
        if str(item).strip()
    }
    return tuple(location.key for location in LOCATIONS if location.key in selected)


def location_options(observed_at: datetime | None = None) -> list[DashboardTimezoneOption]:
    observed = observed_at or datetime.now(UTC)
    return [
        DashboardTimezoneOption(
            key=location.key,
            label=location.label,
            city=location.city,
            country_code=location.country_code,
            flag=location.flag,
            language=location.language,
            timezone=location.timezone,
            currency=location.currency,
            utc_offset=_offset_text(_zone_now(location, observed)),
        )
        for location in LOCATIONS
    ]


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
    # World clocks are calculated from the same UTC instant and the local IANA
    # tzdata. This avoids a per-card external request and keeps every card
    # aligned even when a third-party time API is slow or unavailable.
    fallback = _local_time_fallback(location, observed_at)
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


def _snapshot(
    observed_at: datetime,
    previous: DashboardMarketSnapshot | None,
    location_keys: tuple[str, ...] = DEFAULT_LOCATION_KEYS,
) -> DashboardMarketSnapshot:
    locations = [_LOCATION_BY_KEY[key] for key in location_keys if key in _LOCATION_BY_KEY]
    times = [_fetch_world_time(location, observed_at) for location in locations]
    rates, rate_date, rate_source = _fetch_exchange_rates(previous)
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
        available_timezones=location_options(observed_at),
        exchange_rates=rates,
        rate_date=rate_date,
        time_source=time_source,
        rate_source=rate_source,
    )


def get_dashboard_market_snapshot(
    observed_at: datetime | None = None,
    location_keys: object | None = None,
) -> DashboardMarketSnapshot:
    """Return cached dashboard market context without making it a hard dependency."""

    global _CACHE, _CACHE_AT, _RATE_CACHE, _RATE_CACHE_AT
    now = observed_at or datetime.now(UTC)
    cache_key = normalize_location_keys(location_keys)
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        cached_at = _CACHE_AT.get(cache_key, 0.0)
        if cached is not None and monotonic() - cached_at < _cache_seconds():
            return cached
        previous = cached
        try:
            current = _snapshot(now, previous, cache_key)
        except Exception as exc:  # pragma: no cover - defensive fail-open guard
            logger.warning("Dashboard market snapshot failed: %s", type(exc).__name__)
            current = previous or _snapshot_local_only(now, cache_key)
        _CACHE[cache_key] = current
        _CACHE_AT[cache_key] = monotonic()
        _RATE_CACHE = _rate_only_snapshot(current)
        _RATE_CACHE_AT = _CACHE_AT[cache_key]
        return current


def _rate_only_snapshot(snapshot: DashboardMarketSnapshot) -> DashboardMarketSnapshot:
    """Strip dashboard-only world clocks from a market snapshot."""

    return snapshot.model_copy(
        update={
            "world_times": [],
            "time_source": "system",
        }
    )


def _has_foreign_rates(snapshot: DashboardMarketSnapshot) -> bool:
    return any(
        item.currency != BASE_CURRENCY
        and item.rate is not None
        and item.rate > 0
        for item in snapshot.exchange_rates
    )


def _rate_cache_seconds(snapshot: DashboardMarketSnapshot) -> int:
    # Do not pin a cold-start provider outage for the full normal cache TTL.
    return _cache_seconds() if _has_foreign_rates(snapshot) else 60


def get_exchange_rate_snapshot(
    observed_at: datetime | None = None,
) -> DashboardMarketSnapshot:
    """Return cached FX data without querying the dashboard world clocks.

    The customer storefront loads this after its primary content. Keeping a
    rate-only cache means a cold storefront request performs one provider call
    instead of also waiting for every world-time endpoint.
    """

    global _RATE_CACHE, _RATE_CACHE_AT
    now = observed_at or datetime.now(UTC)
    with _CACHE_LOCK:
        cache_ttl = _cache_seconds()
        if (
            _RATE_CACHE is not None
            and monotonic() - _RATE_CACHE_AT < _rate_cache_seconds(_RATE_CACHE)
        ):
            return _RATE_CACHE
        default_market = _CACHE.get(DEFAULT_LOCATION_KEYS)
        default_market_at = _CACHE_AT.get(DEFAULT_LOCATION_KEYS, 0.0)
        if (
            default_market is not None
            and monotonic() - default_market_at < cache_ttl
            and _has_foreign_rates(default_market)
        ):
            _RATE_CACHE = _rate_only_snapshot(default_market)
            _RATE_CACHE_AT = default_market_at
            return _RATE_CACHE

        previous = _RATE_CACHE
        if previous is None:
            default_market = _CACHE.get(DEFAULT_LOCATION_KEYS)
            if default_market is not None:
                previous = _rate_only_snapshot(default_market)
        rates, rate_date, rate_source = _fetch_exchange_rates(previous)
        current = DashboardMarketSnapshot(
            observed_at=now,
            world_times=[],
            exchange_rates=rates,
            rate_date=rate_date,
            time_source="system",
            rate_source=rate_source,
        )
        _RATE_CACHE = current
        _RATE_CACHE_AT = monotonic()
        return current


def _snapshot_local_only(
    observed_at: datetime,
    location_keys: tuple[str, ...] = DEFAULT_LOCATION_KEYS,
) -> DashboardMarketSnapshot:
    locations = [_LOCATION_BY_KEY[key] for key in location_keys if key in _LOCATION_BY_KEY]
    return DashboardMarketSnapshot(
        observed_at=observed_at,
        world_times=[_local_time_fallback(location, observed_at) for location in locations],
        available_timezones=location_options(observed_at),
        exchange_rates=_fallback_rates(None),
        time_source="system",
        rate_source="fallback",
    )


def reset_dashboard_market_cache() -> None:
    """Clear the process-local cache in tests or after configuration changes."""

    global _CACHE, _CACHE_AT, _RATE_CACHE, _RATE_CACHE_AT
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_AT.clear()
        _RATE_CACHE = None
        _RATE_CACHE_AT = 0.0
