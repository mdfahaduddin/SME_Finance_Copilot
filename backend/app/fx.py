"""Currency conversion and formatting for figures that cross currencies (e.g. lender criteria set in USD
compared with a business that reports in BDT).

Rates are indicative "units per 1 USD", good enough to compare eligibility and costs, never to settle money.
Override or extend them with FX_RATES, a JSON object such as {"BDT": 121.5, "EUR": 0.91}.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger(__name__)

# Units of each currency per 1 USD. Update when rates move materially (or set FX_RATES).
DEFAULT_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "BDT": 122.0, "INR": 85.0, "SGD": 1.35,
    "AUD": 1.52, "CAD": 1.37, "CNY": 7.2, "HKD": 7.8, "AED": 3.67, "MYR": 4.5,
}


class UnknownCurrency(ValueError):
    pass


@lru_cache
def rates() -> dict[str, float]:
    table = dict(DEFAULT_RATES)
    raw = get_settings().fx_rates.strip()
    if raw:
        try:
            extra = json.loads(raw)
            table.update({str(k).upper(): float(v) for k, v in extra.items() if float(v) > 0})
        except (ValueError, TypeError, AttributeError):
            log.warning("FX_RATES is not a JSON object of positive numbers; using the built-in rates")
    return table


def rate(from_currency: str, to_currency: str) -> float:
    """Multiply an amount in `from_currency` by this to get `to_currency`."""
    if from_currency == to_currency:
        return 1.0
    table = rates()
    try:
        return table[to_currency] / table[from_currency]
    except KeyError as e:
        raise UnknownCurrency(f"No exchange rate for {e.args[0]}; add it to FX_RATES") from None


def convert(amount: float, from_currency: str, to_currency: str) -> float:
    return amount * rate(from_currency, to_currency)


def fmt(amount: float, currency: str, decimals: int = 0) -> str:
    """$1,234 / -$1,234 for USD; BDT 1,234 / -BDT 1,234 for other currencies (ASCII-safe for emails)."""
    sign = "-" if amount < 0 else ""
    number = f"{abs(amount):,.{decimals}f}"
    return f"{sign}${number}" if currency == "USD" else f"{sign}{currency} {number}"


def nice(amount: float) -> float:
    """Round to two significant figures, for limits shown to people (610,000 rather than 610,000.00 or 609,756)."""
    if amount <= 0:
        return amount
    return float(f"{amount:.2g}")
