from datetime import date
import pytest
from pydantic import ValidationError
from sublease.cli.init import DEFAULT_TEMPLATES, build_profile

ANSWERS = {
    "name": "East Village room",
    "neighborhood": "East Village",
    "unit_type": "room",
    "bedrooms": 1,
    "window_start": "2026-08-18",
    "window_end": "2026-09-08",
    "allow_split": True,
    "max_split": 3,
    "total_price": 2200,
    "max_people_per_room": 1,
    "gender_preference": None,
    "sources": [{"slug": "nycsublets", "name": "NYC Sublets", "method": "forage"}],
}


def test_build_profile_maps_every_answer():
    p = build_profile(ANSWERS)
    assert p.name == "East Village room"
    assert p.place.neighborhood == "East Village"
    assert p.window.start == date(2026, 8, 18)
    assert p.window.days == 22
    assert p.price.total == 2200
    assert p.sources[0].slug == "nycsublets"


def test_default_templates_are_supplied_when_none_given():
    p = build_profile(ANSWERS)
    assert p.templates.outreach_message == DEFAULT_TEMPLATES["outreach_message"]
    assert "{first_name}" in p.templates.outreach_message


def test_supplied_templates_win_over_the_defaults():
    p = build_profile({**ANSWERS, "outreach_message": "Yo {first_name}"})
    assert p.templates.outreach_message == "Yo {first_name}"


def test_split_settings_are_carried_through():
    p = build_profile({**ANSWERS, "allow_split": False})
    assert p.window.allow_split is False
    assert p.window.max_split == 1


def test_gender_preference_is_optional_and_defaults_to_none():
    assert build_profile(ANSWERS).constraints.gender_preference is None


def test_gender_preference_is_carried_when_given():
    p = build_profile({**ANSWERS, "gender_preference": "male"})
    assert p.constraints.gender_preference == "male"


def test_a_reversed_window_is_rejected_with_a_validation_error():
    with pytest.raises(ValidationError):
        build_profile({**ANSWERS, "window_start": "2026-09-08",
                       "window_end": "2026-08-18"})


def test_missing_price_is_rejected():
    answers = {k: v for k, v in ANSWERS.items() if k != "total_price"}
    with pytest.raises(ValidationError):
        build_profile(answers)


def test_the_default_listing_copy_uses_no_bullet_lines():
    """Facebook's composer turns lines starting '- ' into double bullets."""
    for line in DEFAULT_TEMPLATES["listing_post"].splitlines():
        assert not line.strip().startswith("- ")


def test_the_default_outreach_copy_contains_no_emoticon_traps():
    from sublease.match.drafts import EMOTICON_TRAPS
    for trap in EMOTICON_TRAPS:
        assert trap not in DEFAULT_TEMPLATES["outreach_message"]
