"""Which combination of seekers covers the whole window?

Replaces reference/pipeline/filter_rank.py:229-241, which had two defects:

  * It enumerated `combinations(partials, 2)` and so could only ever propose
    *pairs*. The arrangement that actually filled the prototype author's window
    was a three-person split — the tool could not have surfaced the answer its
    own author found by hand.
  * It built a `set` of `date` objects day by day for every pair, which is
    quadratic in candidates and linear in window length.

Both are fixed here, and `coverage()` runs in two stages with different
optimality guarantees:

  1. A left-to-right interval sweep tries first: track the leftmost uncovered
     day, and among all candidates starting at or before it, pick the one
     extending furthest right; repeat. This is the classic algorithm for
     covering a segment with the fewest intervals, and it is *provably
     optimal* for that objective — if any combination of at most `max_split`
     candidates can fully cover the window, the sweep finds one. Max-gain
     greedy is not optimal here: it can pick the single largest-overlap
     candidate first and strand itself unable to fill the remainder within
     budget, even when a full tiling exists (verified counterexample: a
     10-day window, max_split=2, where a 6-day middle candidate outscores
     either of two 5-day edge candidates that together tile the window
     exactly — max-gain lands at 8/10, the sweep finds the 10/10 tiling).

  2. If full coverage isn't reachable within `max_split`, coverage falls back
     to max-gain greedy to maximise days covered under the hard cap, and
     reports the honest shortfall. Maximising coverage under a hard cap on
     picks is a different (harder) objective with no simple optimal
     algorithm here; the greedy heuristic is not provably optimal for it, but
     is a reasonable approximation and this stage only runs once full
     coverage is already known to be out of reach.
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


def _sweep_full_coverage(spans: list[tuple[Candidate, Interval]], w_start: date,
                          w_end: date, max_split: int) -> list[int] | None:
    """Fewest-intervals full coverage via the classic left-to-right sweep.

    Returns the chosen `spans` indices if the window can be fully covered
    using at most `max_split` of them, else None. Provably optimal for "can
    this window be fully covered, and with which fewest candidates" — see
    the module docstring.
    """
    frontier = w_start
    chosen: list[int] = []
    used: set[int] = set()

    while frontier <= w_end:
        best_index, best_end = None, None
        for index, (_, (start, end)) in enumerate(spans):
            if index in used or start > frontier:
                continue
            if best_end is None or end > best_end:
                best_index, best_end = index, end
        if best_index is None or best_end < frontier:
            return None
        used.add(best_index)
        chosen.append(best_index)
        if len(chosen) > max_split:
            return None
        frontier = best_end + ONE_DAY

    return chosen


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

    swept = _sweep_full_coverage(spans, w_start, w_end, max_split)
    if swept is not None:
        chosen = [spans[index][0] for index in swept]
        return CoveragePlan(window_days=window_days, singles=singles,
                            combination=chosen, combination_days=window_days)

    # Full coverage isn't reachable within max_split: fall back to max-gain
    # greedy to maximise days covered under the cap, reporting the honest
    # shortfall. See module docstring — this stage is a heuristic, not
    # provably optimal.
    uncovered: list[Interval] = [(w_start, w_end)]
    chosen = []
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
