# tests/test_extract_dates.py
from datetime import date
import pytest
from sublease.extract.dates import date_hint_matches, labor_day, memorial_day


@pytest.mark.parametrize("year,expected", [
    (2024, date(2024, 9, 2)),
    (2025, date(2025, 9, 1)),
    (2026, date(2026, 9, 7)),   # the value the prototype hardcoded
    (2027, date(2027, 9, 6)),
    (2028, date(2028, 9, 4)),
])
def test_labor_day_is_the_first_monday_of_september(year, expected):
    assert labor_day(year) == expected


@pytest.mark.parametrize("year,expected", [
    (2026, date(2026, 5, 25)),
    (2027, date(2027, 5, 31)),
])
def test_memorial_day_is_the_last_monday_of_may(year, expected):
    assert memorial_day(year) == expected


@pytest.mark.parametrize("text", [
    "Looking for a sublet in August",
    "ISO a room sept 1",
    "need a place through Labor Day",
    "available 8/20 - 9/1",
    "moving in ASAP",
    "need somewhere for a month",
    "sublet for two weeks",
    "move-in mid September",
    "available end of august",
    "early sept works",
])
def test_date_hint_matches_date_bearing_text(text):
    assert date_hint_matches(text) is True


@pytest.mark.parametrize("text", [
    "Does anyone know a good moving company that does small jobs? Thanks!",
    "Looking for roommate recommendations",
    "",
])
def test_date_hint_rejects_text_with_no_timeframe(text):
    assert date_hint_matches(text) is False


def test_date_hint_is_case_insensitive():
    assert date_hint_matches("LABOR DAY") is True
