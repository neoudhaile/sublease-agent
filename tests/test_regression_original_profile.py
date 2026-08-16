"""The original author's setup, reproduced through the new engine.

The prototype's constants are gone; these are now profile fields. This test is
what makes "port, don't rewrite" checkable — if a refactor changes any household
rule, this fails.

Source of truth: reference/groups.yaml (window) and
reference/pipeline/filter_rank.py:33-60 (household rules).
"""
from datetime import date

from sublease.match.tiering import tier_for
from sublease.match.types import CandidateFacts
from sublease.match.window import classify
from sublease.profile.models import Constraints, Window

ORIGINAL_WINDOW = Window(start=date(2026, 8, 18), end=date(2026, 9, 8))
ORIGINAL_CONSTRAINTS = Constraints(
    max_people_per_room=1,
    multi_room_seekers_ok=True,
    gender_preference="male",
    tier_a_coverage=0.90,
    tier_b_coverage=0.60,
)


def tier(days, **facts):
    return tier_for(CandidateFacts(days_covered=days, **facts),
                    ORIGINAL_CONSTRAINTS, ORIGINAL_WINDOW.days)[0]


def test_the_window_is_twenty_two_days():
    assert ORIGINAL_WINDOW.days == 22


def test_a_full_window_male_seeker_is_tier_a():
    assert tier(22, gender="male") == "A"


def test_a_full_window_female_seeker_is_tier_b_not_excluded():
    assert tier(22, gender="female") == "B"


def test_a_full_window_seeker_of_unstated_gender_is_tier_a():
    assert tier(22, gender=None) == "A"


def test_a_couple_sharing_the_room_is_tier_d():
    assert tier(22, people_in_one_room=2) == "D"


def test_someone_needing_two_rooms_is_not_penalised():
    assert tier(22, people_in_one_room=1, wants_multiple_rooms=True) == "A"


def test_the_tier_boundaries_land_where_the_prototype_put_them():
    assert tier(20) == "A"     # 0.909
    assert tier(19) == "B"     # 0.864
    assert tier(14) == "B"     # 0.636
    assert tier(13) == "C"     # 0.591


def test_window_classification_matches_the_prototype_on_known_ranges():
    w = (ORIGINAL_WINDOW.start, ORIGINAL_WINDOW.end)
    assert classify(date(2026, 8, 18), date(2026, 9, 8), *w) == ("full-window", 22)
    assert classify(date(2026, 8, 20), date(2026, 9, 1), *w) == ("inside", 13)
    assert classify(date(2026, 8, 1), date(2026, 9, 1), *w) == ("overlap", 15)
    assert classify(date(2026, 9, 15), date(2026, 10, 30), *w) == (None, 0)
