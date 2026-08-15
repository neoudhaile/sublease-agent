from datetime import date
import pytest
from sublease.match.window import classify

W_START, W_END = date(2026, 8, 18), date(2026, 9, 8)   # 22 days inclusive


def c(start, end):
    return classify(start, end, W_START, W_END)


def test_exact_match_is_full_window():
    assert c(date(2026, 8, 18), date(2026, 9, 8)) == ("full-window", 22)


def test_range_strictly_inside_the_window_is_inside():
    fit, days = c(date(2026, 8, 20), date(2026, 9, 1))
    assert (fit, days) == ("inside", 13)


def test_range_spanning_beyond_both_ends_is_wants_more():
    fit, days = c(date(2026, 8, 1), date(2026, 9, 30))
    assert (fit, days) == ("wants-more", 22)


def test_range_starting_before_and_ending_inside_is_overlap():
    fit, days = c(date(2026, 8, 1), date(2026, 9, 1))
    assert (fit, days) == ("overlap", 15)


def test_range_starting_inside_and_ending_after_is_overlap():
    fit, days = c(date(2026, 8, 25), date(2026, 10, 1))
    assert (fit, days) == ("overlap", 15)


def test_range_entirely_after_the_window_does_not_match():
    assert c(date(2026, 9, 15), date(2026, 10, 30)) == (None, 0)


def test_range_entirely_before_the_window_does_not_match():
    assert c(date(2026, 6, 1), date(2026, 7, 1)) == (None, 0)


def test_open_end_runs_to_the_window_end():
    fit, days = c(date(2026, 8, 22), None)
    assert (fit, days) == ("inside", 18)


def test_open_start_runs_from_the_window_start():
    fit, days = c(None, date(2026, 9, 1))
    assert (fit, days) == ("inside", 15)


def test_both_dates_open_does_not_match():
    assert c(None, None) == (None, 0)


def test_reversed_dates_are_swapped_rather_than_rejected():
    assert c(date(2026, 9, 8), date(2026, 8, 18)) == ("full-window", 22)


def test_single_day_overlap_at_the_window_start_counts():
    fit, days = c(date(2026, 8, 1), date(2026, 8, 18))
    assert (fit, days) == ("overlap", 1)


def test_single_day_overlap_at_the_window_end_counts():
    fit, days = c(date(2026, 9, 8), date(2026, 10, 1))
    assert (fit, days) == ("overlap", 1)


def test_one_day_before_the_window_does_not_match():
    assert c(date(2026, 8, 1), date(2026, 8, 17)) == (None, 0)


@pytest.mark.parametrize("start,end", [
    (date(2026, 8, 18), date(2026, 9, 8)),
    (date(2026, 8, 20), date(2026, 9, 1)),
])
def test_days_covered_never_exceeds_the_window_length(start, end):
    assert c(start, end)[1] <= 22
