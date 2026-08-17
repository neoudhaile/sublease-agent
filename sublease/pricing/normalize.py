"""Convert a stated price to a per-night figure, or admit it can't be done.

The canonical unit across the whole pricing feature is `nightly_price`. Every
price form in the design doc converts to it via this one function. Nothing
here reads a clock or touches the network — every date is a parameter, and a
comp whose price cannot be converted is DROPPED, never estimated: a wrong
comp moves the median invisibly, a missing one just shrinks the sample.

`price_amount` must already be a clean number — string cleanup (stripping
"$", commas, "/mo" suffixes, etc.) is `sublease.extract.runner.parse_price_amount`'s
job, upstream of this. `start`/`end` must already be parsed `date` objects;
parsing ISO strings out of storage is the caller's job, not this module's.
"""
from __future__ import annotations

from datetime import date

AVERAGE_DAYS_PER_MONTH = 30.4
DAYS_PER_WEEK = 7


def normalize_nightly(price_amount: float | int | None, price_unit: str | None,
                       start: date | None = None, end: date | None = None) -> float | None:
    """Convert a stated price to $/night, or None if it can't be derived.

    | price_unit | conversion                                   |
    |------------|----------------------------------------------|
    | "night"    | as-is                                         |
    | "week"     | / 7                                            |
    | "month"    | / 30.4 (average month length)                  |
    | "period"   | / inclusive nights between start and end       |

    Returns None (never raises, never guesses) when:
      * `price_amount` or `price_unit` is missing.
      * `price_amount` is zero or negative — a nightly_price this module
        produces must never reach the comps table as zero/negative.
      * `price_unit` is "period" and `start` or `end` is missing.
      * the inclusive night count between `start` and `end` is zero or
        negative (e.g. `end` before `start`).
      * `price_unit` is anything else unrecognised.
    """
    if price_amount is None or price_unit is None:
        return None
    if isinstance(price_amount, bool):  # bool is an int subclass; reject explicitly
        return None
    try:
        amount = float(price_amount)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None

    if price_unit == "night":
        return amount
    if price_unit == "week":
        return amount / DAYS_PER_WEEK
    if price_unit == "month":
        return amount / AVERAGE_DAYS_PER_MONTH
    if price_unit == "period":
        if start is None or end is None:
            return None
        nights = (end - start).days + 1
        if nights <= 0:
            return None
        return amount / nights
    return None
