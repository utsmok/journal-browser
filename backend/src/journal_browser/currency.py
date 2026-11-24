"""EUR conversion for prices.

Runs when the APC columns are denormalized (harvest.denorm.refresh_apcs),
so prices reach the API already in EUR. Top-level module on purpose: the
harvest layer cannot import from services.
"""

import logging
from datetime import date

from currency_converter import CurrencyConverter

logger = logging.getLogger(__name__)

_converter: CurrencyConverter | None = None
_converter_year: int | None = None
_init_failed = False
_no_rate_logged: set[str] = set()
_rates: dict[tuple[int, str], float | None] = {}


def _rate_table(year: int) -> CurrencyConverter | None:
    """The bundled ECB rate table, loaded once per process and per year."""
    global _converter, _converter_year, _init_failed
    if _converter is not None and _converter_year == year:
        return _converter
    if _init_failed:
        return None
    try:
        _converter = CurrencyConverter(fallback_on_missing_rate=True, fallback_on_wrong_date=True)
        _converter_year = year
    except Exception:
        _init_failed = True
        logger.warning("currency rate table init failed", exc_info=True)
    return _converter


def year_rate(currency: str) -> float | None:
    """EUR units per 1 `currency` at Jan 1 of the current year, or None.

    The ECB publishes no fixing on Jan 1 (holiday), so missing-rate linear
    interpolation supplies the Jan 1 rate; fallback_on_wrong_date handles
    dates outside the bundle. The bundle covers the ECB reference rates
    only, so currencies such as UAH or EGP have no rate: None means
    "cannot convert" and callers keep the source currency. A missing rate
    is logged once per currency, because one refresh asks thousands of
    times.
    """
    code = (currency or "").upper()
    if len(code) != 3 or not code.isalpha():
        return None
    if code == "EUR":
        return 1.0
    year = date.today().year
    key = (year, code)
    if key in _rates:
        return _rates[key]
    table = _rate_table(year)
    rate: float | None = None
    if table is not None:
        try:
            rate = float(table.convert(1, code, "EUR", date=date(year, 1, 1)))
        except Exception:
            if code not in _no_rate_logged:
                _no_rate_logged.add(code)
                logger.warning("no euro exchange rate for %s; prices stay in %s", code, code)
    _rates[key] = rate
    return rate


def to_eur(price: float, currency: str) -> tuple[str, float]:
    """Convert a price to EUR; keep the source currency when no rate exists.

    Returns (currency, price).
    """
    rate = year_rate(currency)
    if rate is None or rate <= 0:
        return currency, price
    return "EUR", round(price * rate, 2)
