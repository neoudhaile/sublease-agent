"""Date facts the extraction prompt needs, computed rather than hardcoded.

The prototype baked "Today's date is 2026-08-11" and "Labor Day 2026 is
September 7" into its prompt (reference/pipeline/extract.py:21-23). For any
other user, or the same user a year later, every relative phrase resolved to the
wrong year. Everything here is derived from a reference date the caller supplies.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

# Recall-oriented prefilter: a post with no date-ish token cannot state a
# timeframe, so it never needs to reach a model.
# Ported from reference/pipeline/extract.py:13-17.
DATE_HINT = re.compile(
    r"(aug|sep\b|sept|september|labor\s*day|\b\d{1,2}\s*[/.-]\s*\d{1,2}\b|"
    r"week|month|asap|move.?in|mid|early|late|end of)",
    re.IGNORECASE,
)

MONDAY = 0


def labor_day(year: int) -> date:
    """First Monday of September."""
    for day in range(1, 8):
        candidate = date(year, 9, day)
        if candidate.weekday() == MONDAY:
            return candidate
    raise AssertionError("unreachable: September always contains a Monday in 1-7")


def memorial_day(year: int) -> date:
    """Last Monday of May."""
    last = calendar.monthrange(year, 5)[1]
    for day in range(last, last - 7, -1):
        candidate = date(year, 5, day)
        if candidate.weekday() == MONDAY:
            return candidate
    raise AssertionError("unreachable: May always contains a Monday in its last week")


def date_hint_matches(text: str) -> bool:
    return bool(DATE_HINT.search(text or ""))
