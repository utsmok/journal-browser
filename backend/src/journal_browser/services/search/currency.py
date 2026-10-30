import logging
from datetime import date

from currency_converter import CurrencyConverter

from ..source_health import record_degraded

logger = logging.getLogger(__name__)

_converter: CurrencyConverter | None = None
_converter_year: int | None = None


def _year_rate(currency: str) -> float | None:
    """EUR units per 1 `currency` at Jan 1 of the current year.

    The ECB publishes no fixing on Jan 1 (holiday), so missing-rate linear
    interpolation supplies the Jan 1 rate; fallback_on_wrong_date handles
    dates outside a currency's quoted range. Bundled ECB data refreshes with
    the package; None means "cannot convert" and callers keep the source
    currency.
    """
    global _converter, _converter_year
    year = date.today().year
    if _converter is None or _converter_year != year:
        try:
            _converter = CurrencyConverter(
                fallback_on_missing_rate=True, fallback_on_wrong_date=True
            )
            _converter_year = year
        except Exception:
            logger.warning("currency rate table init failed", exc_info=True)
            record_degraded("currency-rates", "rate table init failed")
            return None
    try:
        return float(_converter.convert(1, currency, "EUR", date=date(year, 1, 1)))
    except Exception:
        logger.warning("currency conversion failed for %s", currency, exc_info=True)
        record_degraded("currency-rates", f"conversion failed for {currency}")
        return None


def _to_eur(price: float, currency: str) -> tuple[str, float]:
    """Standardize a list price to EUR; keep the source currency on failure.

    Returns (currency, price), matching the list_price tuple convention.
    """
    if currency == "EUR":
        return currency, price
    # Deferred: _year_rate resolves through the package namespace, keeping
    # the search-module monkeypatch seam (tests/test_search_scopes.py) live.
    from journal_browser.services import search

    rate = search._year_rate(currency)
    if rate is None or rate <= 0:
        return currency, price
    return "EUR", round(price * rate, 2)
