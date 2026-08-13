from datetime import date
import pytest
from pydantic import ValidationError
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)


def make_window(**kw):
    base = {"start": date(2026, 8, 18), "end": date(2026, 9, 8)}
    return Window(**{**base, **kw})


def test_window_days_is_inclusive():
    assert make_window().days == 22


def test_window_rejects_end_before_start():
    with pytest.raises(ValidationError):
        Window(start=date(2026, 9, 8), end=date(2026, 8, 18))


def test_window_defaults_allow_split_on_with_max_three():
    w = make_window()
    assert w.allow_split is True
    assert w.max_split == 3


def test_max_split_is_forced_to_one_when_split_disallowed():
    assert make_window(allow_split=False, max_split=3).max_split == 1


def test_price_derives_total_from_nightly():
    assert Price(nightly=100).total_for(22) == 2200


def test_price_derives_nightly_from_total():
    assert Price(total=2200).nightly_for(22) == 100


def test_price_requires_one_of_nightly_or_total():
    with pytest.raises(ValidationError):
        Price()


def test_constraint_defaults_match_the_prototype():
    c = Constraints()
    assert c.max_people_per_room == 1
    assert c.multi_room_seekers_ok is True
    assert c.gender_preference is None
    assert (c.tier_a_coverage, c.tier_b_coverage) == (0.90, 0.60)


def test_tier_b_coverage_must_not_exceed_tier_a():
    with pytest.raises(ValidationError):
        Constraints(tier_a_coverage=0.5, tier_b_coverage=0.9)


def test_template_placeholders_are_validated():
    with pytest.raises(ValidationError):
        Templates(outreach_message="Hi {nickname}", listing_post="x")


def test_templates_accept_the_supported_placeholders():
    t = Templates(
        outreach_message="Hi {first_name}, saw your post in {group} for {their_dates}",
        listing_post="Room available.",
    )
    assert "{first_name}" in t.outreach_message


def test_profile_round_trips_through_json():
    p = Profile(
        name="East Village room",
        place=Place(neighborhood="East Village", unit_type="room", bedrooms=1),
        window=make_window(),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="Room."),
        sources=[SourceConfig(platform="facebook", slug="nycsublets",
                              name="NYC Sublets", method="forage")],
    )
    assert Profile.model_validate_json(p.model_dump_json()) == p
