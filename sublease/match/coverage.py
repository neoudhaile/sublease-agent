"""Which combination of seekers covers the whole window?

Replaces reference/pipeline/filter_rank.py:229-241, which had two defects:

  * It enumerated `combinations(partials, 2)` and so could only ever propose
    *pairs*. The arrangement that actually filled the prototype author's window
    was a three-person split — the tool could not have surfaced the answer its
    own author found by hand.
  * It built a `set` of `date` objects day by day for every pair, which is
    quadratic in candidates and linear in window length.

Both are fixed here: greedy set-cover up to `max_split` seekers, over intervals
rather than day sets. Greedy is not provably optimal, but for interval cover on
one timeline with a handful of picks it matches exhaustive search in practice
while staying linear per pick.
"""
from __future__ import annotations

from datetime import date, timedelta

from sublease.match.types import Candidate, CoveragePlan

Interval = tuple[date, date]
ONE_DAY = timedelta(days=1)
DEFAULT_MAX_SPLIT = 3
DEFAULT_SLACK = 2
MAX_SINGLES_REPORTED = 10


def _days(interval: Interval) -> int:
    return (interval[1] - interval[0]).days + 1


def overlap_days(a: Interval, b: Interval) -> int:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return max((hi - lo).days + 1, 0)


def clip(candidate: Candidate, w_start: date, w_end: date) -> Interval | None:
    """The part of a candidate's availability that falls inside the window."""
    start = max(candidate.wants_start or w_start, w_start)
    end = min(candidate.wants_end or w_end, w_end)
    return (start, end) if start <= end else None


def subtract(uncovered: list[Interval], taken: Interval) -> list[Interval]:
    """Remove `taken` from each remaining gap, splitting where it lands inside."""
    remaining: list[Interval] = []
    for lo, hi in uncovered:
        if taken[1] < lo or taken[0] > hi:
            remaining.append((lo, hi))
            continue
        if lo < taken[0]:
            remaining.append((lo, taken[0] - ONE_DAY))
        if hi > taken[1]:
            remaining.append((taken[1] + ONE_DAY, hi))
    return remaining


def coverage(candidates: list[Candidate], w_start: date, w_end: date,
             max_split: int = DEFAULT_MAX_SPLIT,
             near_complete_slack: int = DEFAULT_SLACK) -> CoveragePlan:
    window_days = (w_end - w_start).days + 1

    singles = sorted(
        (c for c in candidates if c.days_covered >= window_days - near_complete_slack),
        key=lambda c: -c.days_covered,
    )[:MAX_SINGLES_REPORTED]

    spans: list[tuple[Candidate, Interval]] = []
    for candidate in candidates:
        interval = clip(candidate, w_start, w_end)
        if interval is not None:
            spans.append((candidate, interval))

    uncovered: list[Interval] = [(w_start, w_end)]
    chosen: list[Candidate] = []
    used: set[int] = set()

    while uncovered and len(chosen) < max_split:
        best_index, best_gain = None, 0
        for index, (_, interval) in enumerate(spans):
            if index in used:
                continue
            gain = sum(overlap_days(interval, gap) for gap in uncovered)
            if gain > best_gain:
                best_index, best_gain = index, gain
        if best_index is None:
            break
        used.add(best_index)
        candidate, interval = spans[best_index]
        chosen.append(candidate)
        uncovered = subtract(uncovered, interval)

    covered = window_days - sum(_days(gap) for gap in uncovered)
    return CoveragePlan(window_days=window_days, singles=singles,
                        combination=chosen, combination_days=covered)
