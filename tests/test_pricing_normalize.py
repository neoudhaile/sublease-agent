# tests/test_pricing_normalize.py
"""Table-driven tests for normalize_nightly — every form in the design doc's
normalization table, plus every rejection case. Hand-written, not carried
over from the plan (the plan supplies no test code for this task)."""
from datetime import date

import pytest

from sublease.pricing.normalize import normalize_nightly


# -- conversions that must succeed -------------------------------------

def test_night_is_identity():
    assert normalize_nightly(60, "night") == 60


def test_week_divides_by_seven():
    assert normalize_nightly(350, "week") == pytest.approx(50.0)


def test_month_divides_by_average_month_length():
    # $1400/mo -> 1400 / 30.4, not 1400 / 30 and not 1400 / 31.
    assert normalize_nightly(1400, "month") == pytest.approx(46.0526315789, rel=1e-9)


def test_period_divides_by_inclusive_night_count():
    # Aug 18 - Sep 8 inclusive is 22 nights (14 remaining in Aug + 8 in Sep),
    # not 21 — a fencepost slip here would silently skew the median rather
    # than raise, so it's pinned directly against the day count.
    start, end = date(2026, 8, 18), date(2026, 9, 8)
    assert (end - start).days + 1 == 22
    assert normalize_nightly(1800, "period", start, end) == pytest.approx(1800 / 22)


def test_period_single_day_is_one_night_not_zero():
    # start == end is a valid one-night stay, inclusive counting.
    d = date(2026, 8, 18)
    assert normalize_nightly(100, "period", d, d) == pytest.approx(100.0)


# -- rejections: must return None, never raise, never guess -------------

def test_missing_amount_is_none():
    assert normalize_nightly(None, "night") is None


def test_missing_unit_is_none():
    assert normalize_nightly(60, None) is None


def test_zero_amount_is_none():
    assert normalize_nightly(0, "night") is None


def test_negative_amount_is_none():
    assert normalize_nightly(-60, "night") is None


def test_zero_amount_period_is_none_even_with_valid_dates():
    start, end = date(2026, 8, 18), date(2026, 9, 8)
    assert normalize_nightly(0, "period", start, end) is None


def test_period_without_dates_is_none():
    assert normalize_nightly(1800, "period") is None


def test_period_with_only_start_is_none():
    assert normalize_nightly(1800, "period", date(2026, 8, 18), None) is None


def test_period_with_only_end_is_none():
    assert normalize_nightly(1800, "period", None, date(2026, 9, 8)) is None


def test_period_end_before_start_is_none_not_negative():
    # A zero/negative night range must never produce a negative or infinite
    # per-night figure — it's dropped.
    start, end = date(2026, 9, 8), date(2026, 8, 18)
    assert normalize_nightly(1800, "period", start, end) is None


def test_unrecognised_unit_is_none():
    assert normalize_nightly(60, "fortnight") is None


def test_bool_amount_is_rejected():
    # bool is an int subclass in Python; a stray True/False must not be
    # silently treated as 1/0.
    assert normalize_nightly(True, "night") is None
