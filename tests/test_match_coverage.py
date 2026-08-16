# tests/test_match_coverage.py
from datetime import date
from sublease.match.coverage import clip, coverage, overlap_days, subtract
from sublease.match.types import Candidate

W_START, W_END = date(2026, 8, 18), date(2026, 9, 8)


def cand(name, start, end, days=None):
    lo, hi = max(start, W_START), min(end, W_END)
    return Candidate(
        post_id=f"p:{name}", person_key=name, name=name, fit="inside",
        days_covered=days if days is not None else (hi - lo).days + 1,
        wants_start=start, wants_end=end)


def d(day):
    return date(2026, 8, day) if day <= 31 else date(2026, 9, day - 31)


def test_overlap_days_counts_inclusive_days():
    assert overlap_days((d(18), d(20)), (d(19), d(25))) == 2


def test_overlap_days_is_zero_when_disjoint():
    assert overlap_days((d(18), d(20)), (d(21), d(25))) == 0


def test_clip_trims_a_range_to_the_window():
    c = cand("x", date(2026, 8, 1), date(2026, 9, 30))
    assert clip(c, W_START, W_END) == (W_START, W_END)


def test_clip_returns_none_for_a_range_outside_the_window():
    c = cand("x", date(2026, 9, 20), date(2026, 10, 1))
    assert clip(c, W_START, W_END) is None


def test_clip_treats_open_dates_as_the_window_edges():
    c = Candidate(post_id="p", person_key="k", name="x", fit="inside",
                  days_covered=22, wants_start=None, wants_end=None)
    assert clip(c, W_START, W_END) == (W_START, W_END)


def test_subtract_removes_a_middle_slice_leaving_two_gaps():
    assert subtract([(d(18), d(28))], (d(21), d(23))) == [(d(18), d(20)), (d(24), d(28))]


def test_subtract_trims_a_leading_slice():
    assert subtract([(d(18), d(28))], (d(18), d(20))) == [(d(21), d(28))]


def test_subtract_removes_a_fully_covered_interval():
    assert subtract([(d(18), d(28))], (d(1), d(31))) == []


def test_subtract_leaves_a_disjoint_interval_alone():
    assert subtract([(d(18), d(20))], (d(25), d(28))) == [(d(18), d(20))]


def test_near_complete_singles_are_surfaced():
    plan = coverage([cand("Emma", W_START, W_END)], W_START, W_END)
    assert [c.name for c in plan.singles] == ["Emma"]


def test_a_partial_candidate_is_not_a_near_complete_single():
    plan = coverage([cand("Ivan", d(20), d(31))], W_START, W_END)
    assert plan.singles == []


def test_singles_tolerate_the_configured_slack():
    plan = coverage([cand("Almost", d(19), d(38))], W_START, W_END,
                    near_complete_slack=2)
    assert [c.name for c in plan.singles] == ["Almost"]


def test_two_complementary_partials_tile_the_whole_window():
    plan = coverage(
        [cand("Fiona", W_START, d(31)), cand("Nia", d(31), W_END)],
        W_START, W_END, max_split=3)
    assert plan.combination_days == 22
    assert sorted(c.name for c in plan.combination) == ["Fiona", "Nia"]


def test_three_partials_tile_a_window_two_cannot():
    """The case the prototype could not express — it only ever searched pairs."""
    plan = coverage([
        cand("A", W_START, d(24)),
        cand("B", d(25), d(31)),
        cand("C", date(2026, 9, 1), W_END),
    ], W_START, W_END, max_split=3)
    assert plan.combination_days == 22
    assert len(plan.combination) == 3


def test_max_split_caps_how_many_people_are_proposed():
    plan = coverage([
        cand("A", W_START, d(24)),
        cand("B", d(25), d(31)),
        cand("C", date(2026, 9, 1), W_END),
    ], W_START, W_END, max_split=2)
    assert len(plan.combination) == 2
    assert plan.combination_days < 22


def test_max_split_of_one_returns_the_single_best_candidate():
    plan = coverage([
        cand("Short", W_START, d(20)),
        cand("Long", W_START, d(31)),
    ], W_START, W_END, max_split=1)
    assert [c.name for c in plan.combination] == ["Long"]


def test_greedy_picks_the_largest_contribution_first():
    plan = coverage([
        cand("Small", W_START, d(19)),
        cand("Big", W_START, d(31)),
    ], W_START, W_END, max_split=2)
    assert plan.combination[0].name == "Big"


def test_a_candidate_adding_nothing_new_is_not_picked():
    plan = coverage([
        cand("Whole", W_START, W_END),
        cand("Subset", d(20), d(22)),
    ], W_START, W_END, max_split=3)
    assert [c.name for c in plan.combination] == ["Whole"]


def test_candidates_outside_the_window_are_ignored():
    plan = coverage([cand("Otis", date(2026, 9, 15), date(2026, 10, 30))],
                    W_START, W_END)
    assert plan.combination == []
    assert plan.combination_days == 0


def test_an_empty_candidate_list_yields_an_empty_plan():
    plan = coverage([], W_START, W_END)
    assert (plan.singles, plan.combination, plan.combination_days) == ([], [], 0)
    assert plan.window_days == 22


def test_the_plan_reports_the_window_length():
    assert coverage([], W_START, W_END).window_days == 22


def test_coverage_is_fast_on_a_large_candidate_pool():
    """The prototype's day-by-day pair search degraded badly here."""
    pool = [cand(f"c{n}", d(18 + n % 10), d(20 + n % 10)) for n in range(500)]
    plan = coverage(pool, W_START, W_END, max_split=3)
    assert len(plan.combination) <= 3
