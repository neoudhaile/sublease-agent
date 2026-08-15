import pytest
from sublease.match.tiering import tier_for
from sublease.match.types import CandidateFacts
from sublease.profile.models import Constraints

WINDOW = 22


def tier(days, **facts):
    constraints = facts.pop("constraints", Constraints())
    return tier_for(CandidateFacts(days_covered=days, **facts), constraints, WINDOW)


def test_full_coverage_solo_is_tier_a():
    assert tier(22)[0] == "A"


def test_coverage_at_the_tier_a_threshold_is_tier_a():
    assert tier(20)[0] == "A"          # 20/22 = 0.909


def test_coverage_between_the_thresholds_is_tier_b():
    assert tier(15)[0] == "B"          # 15/22 = 0.682


def test_coverage_below_the_tier_b_threshold_is_tier_c():
    assert tier(10)[0] == "C"          # 10/22 = 0.455


def test_two_people_in_one_room_is_the_tier_d_dealbreaker():
    label, reason = tier(22, people_in_one_room=2)
    assert label == "D"
    assert "one room" in reason


def test_the_dealbreaker_outranks_perfect_coverage():
    assert tier(22, people_in_one_room=3)[0] == "D"


def test_someone_needing_two_separate_rooms_is_not_a_dealbreaker():
    """One person per room is fine — only one of them takes this room."""
    label, reason = tier(22, people_in_one_room=1, wants_multiple_rooms=True)
    assert label == "A"
    assert "2 rooms" in reason


def test_unknown_occupancy_is_treated_as_solo():
    assert tier(22, people_in_one_room=None)[0] == "A"


def test_a_relaxed_max_people_per_room_admits_a_couple():
    relaxed = Constraints(max_people_per_room=2)
    assert tier(22, people_in_one_room=2, constraints=relaxed)[0] == "A"
    assert tier(22, people_in_one_room=3, constraints=relaxed)[0] == "D"


def test_matching_the_gender_preference_is_noted_but_does_not_promote():
    prefers_male = Constraints(gender_preference="male")
    label, reason = tier(22, gender="male", constraints=prefers_male)
    assert label == "A"
    assert "preference" in reason


def test_not_matching_the_gender_preference_costs_exactly_one_tier():
    prefers_male = Constraints(gender_preference="male")
    label, reason = tier(22, gender="female", constraints=prefers_male)
    assert label == "B"
    assert "ranked just below" in reason


def test_a_soft_preference_never_demotes_past_tier_c():
    prefers_male = Constraints(gender_preference="male")
    assert tier(10, gender="female", constraints=prefers_male)[0] == "C"


def test_a_soft_preference_never_excludes_anyone():
    prefers_male = Constraints(gender_preference="male")
    assert tier(22, gender="female", constraints=prefers_male)[0] != "D"


def test_gender_is_ignored_entirely_when_no_preference_is_set():
    for gender in ("male", "female", None):
        assert tier(22, gender=gender)[0] == "A"


def test_unstated_gender_is_never_penalised_even_with_a_preference():
    prefers_male = Constraints(gender_preference="male")
    label, reason = tier(22, gender=None, constraints=prefers_male)
    assert label == "A"
    assert "unstated" in reason


def test_custom_coverage_thresholds_are_honored():
    strict = Constraints(tier_a_coverage=0.99, tier_b_coverage=0.95)
    assert tier(22, constraints=strict)[0] == "A"
    assert tier(21, constraints=strict)[0] == "B"     # 0.954
    assert tier(20, constraints=strict)[0] == "C"     # 0.909


def test_the_reason_always_states_the_days_covered():
    assert "15/22 days" in tier(15)[1]


def test_a_zero_length_window_does_not_divide_by_zero():
    assert tier_for(CandidateFacts(days_covered=0), Constraints(), 0)[0] == "C"


def test_defaults_reproduce_the_prototypes_household_rules():
    """The original author's setup: no couples, prefers male, 0.9/0.6 thresholds."""
    original = Constraints(gender_preference="male")
    assert tier(22, gender="male", constraints=original)[0] == "A"
    assert tier(22, gender="female", constraints=original)[0] == "B"
    assert tier(22, people_in_one_room=2, constraints=original)[0] == "D"
    assert tier(14, gender="male", constraints=original)[0] == "B"


# Tests for multi_room_seekers_ok dealbreaker
def test_multi_room_seekers_not_ok_with_multiple_rooms_is_tier_d():
    """Test 1: multi_room_seekers_ok=False + wants_multiple_rooms=True → tier D"""
    no_multi = Constraints(multi_room_seekers_ok=False)
    label, reason = tier(22, wants_multiple_rooms=True, constraints=no_multi)
    assert label == "D"
    assert "multiple rooms" in reason


def test_multi_room_seekers_not_ok_with_single_room_is_unaffected():
    """Test 2: multi_room_seekers_ok=False + wants_multiple_rooms=False → unaffected"""
    no_multi = Constraints(multi_room_seekers_ok=False)
    assert tier(22, wants_multiple_rooms=False, constraints=no_multi)[0] == "A"


def test_multi_room_seekers_ok_by_default_with_multiple_rooms():
    """Test 3: multi_room_seekers_ok=True (default) + wants_multiple_rooms=True → tier A with note"""
    label, reason = tier(22, wants_multiple_rooms=True)
    assert label == "A"
    assert "2 rooms" in reason


def test_occupancy_dealbreaker_takes_precedence_over_multi_room():
    """Test 4: candidate tripping both dealbreakers → tier D with occupancy reason"""
    no_multi = Constraints(max_people_per_room=1, multi_room_seekers_ok=False)
    label, reason = tier(22, people_in_one_room=2, wants_multiple_rooms=True, constraints=no_multi)
    assert label == "D"
    assert "one room" in reason  # occupancy reason takes precedence
