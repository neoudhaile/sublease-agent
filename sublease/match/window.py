"""Does this seeker's requested range overlap the user's window, and by how much?

Ported from reference/pipeline/filter_rank.py:72-91.

Open dates are treated as availability, not as missing data. Someone who says
"from Aug 22, end flexible" is available through the end of the window, and a
tool that discarded them for an absent end date would drop good candidates.
"""
from __future__ import annotations

from datetime import date

from sublease.match.types import Fit


def classify(start: date | None, end: date | None,
             w_start: date, w_end: date) -> tuple[Fit | None, int]:
    """Return (fit, days_covered). (None, 0) means no overlap at all."""
    if start is None and end is None:
        return None, 0

    if start is not None and end is not None and end < start:
        start, end = end, start

    start = start if start is not None else w_start
    end = end if end is not None else w_end
    if end < start:
        return None, 0

    overlap_start = max(start, w_start)
    overlap_end = min(end, w_end)
    days = (overlap_end - overlap_start).days + 1
    if days <= 0:
        return None, 0

    window_days = (w_end - w_start).days + 1
    if start >= w_start and end <= w_end:
        return ("full-window" if days >= window_days else "inside"), days
    if start <= w_start and end >= w_end:
        return "wants-more", days
    return "overlap", days
