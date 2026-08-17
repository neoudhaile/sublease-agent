from datetime import date
import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from sublease.cli.init import (
    DEFAULT_TEMPLATES, build_profile, suggested_nightly_price,
)
from sublease.cli.main import app
from sublease.errors import ConfigError
from sublease.pricing.comps import CompSet
from sublease.pricing.service import PricingResult
from sublease.profile.models import Place
from sublease.store.db import connect, migrate
from sublease.store.repositories import ProfileRepo
from tests.fakes import FakeProvider

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


# --- Fix round 1 -----------------------------------------------------------
# Finding 1: a mistyped date must not crash `build_profile` with a bare
# stdlib traceback — it must raise a typed, plain-language error naming the
# offending field.

def test_a_malformed_date_raises_a_clear_typed_error_naming_the_field():
    with pytest.raises(ConfigError) as exc_info:
        build_profile({**ANSWERS, "window_start": "08/18/2026"})
    message = str(exc_info.value)
    assert "window_start" in message
    assert "YYYY-MM-DD" in message


def test_a_malformed_end_date_also_names_its_own_field():
    with pytest.raises(ConfigError) as exc_info:
        build_profile({**ANSWERS, "window_end": "not a date"})
    assert "window_end" in str(exc_info.value)


# Finding 2: running `init` twice must not silently create a second profile.
# ProfileRepo.save() must UPDATE when given a profile with an existing id,
# and ProfileRepo.list() must return profiles in a deterministic order so
# "the active profile" is a stable concept.

def test_saving_a_profile_with_an_existing_id_updates_not_inserts(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    repo = ProfileRepo(conn)

    first = repo.save(build_profile(ANSWERS))
    assert first.id is not None

    corrected = build_profile({**ANSWERS, "name": "Corrected name"})
    corrected.id = first.id
    repo.save(corrected)

    all_profiles = repo.list()
    assert len(all_profiles) == 1
    assert all_profiles[0].name == "Corrected name"


def test_profile_repo_list_returns_a_deterministic_order(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    repo = ProfileRepo(conn)

    first = repo.save(build_profile({**ANSWERS, "name": "First"}))
    second = repo.save(build_profile({**ANSWERS, "name": "Second"}))

    assert [p.id for p in repo.list()] == [first.id, second.id]
    assert [p.id for p in repo.list()] == [first.id, second.id]  # stable on repeat


def test_running_init_twice_offers_replace_or_cancel_instead_of_duplicating(
        tmp_path, monkeypatch):
    """The CLI-level scenario the finding actually describes: a user runs
    `init` twice (e.g. to fix a typo) and must be asked, not silently given
    a second profile that `doctor` and later commands never see."""
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    runner = CliRunner()

    first_run = "\n".join([
        "My sublet", "East Village", "room",
        "2026-08-18", "2026-09-08", "2200", "y", "1", "none", "",
    ]) + "\n"
    result1 = runner.invoke(app, ["init"], input=first_run)
    assert result1.exit_code == 0, result1.output

    conn = connect(tmp_path / "sublease.db")
    assert [p.name for p in ProfileRepo(conn).list()] == ["My sublet"]

    # Second run, replacing: confirm "y", then re-answer everything.
    replace_run = "y\n" + "\n".join([
        "My sublet v2", "East Village", "room",
        "2026-08-19", "2026-09-09", "2300", "y", "1", "none", "",
    ]) + "\n"
    result2 = runner.invoke(app, ["init"], input=replace_run)
    assert result2.exit_code == 0, result2.output
    assert "already exists" in result2.output.lower()

    profiles = ProfileRepo(conn).list()
    assert [p.name for p in profiles] == ["My sublet v2"]  # replaced, not duplicated

    # Third run, cancelling: the database must be untouched.
    cancel_run = "n\n"
    result3 = runner.invoke(app, ["init"], input=cancel_run)
    assert result3.exit_code == 0, result3.output
    assert "cancel" in result3.output.lower()

    profiles_after_cancel = ProfileRepo(conn).list()
    assert [p.name for p in profiles_after_cancel] == ["My sublet v2"]


# Finding 3: the gender-preference prompt must say, in plain words, that it
# never excludes anyone. Not unit-testable beyond checking the wording
# reaches the terminal, so drive `init` end-to-end via CliRunner (no network,
# no real interactive terminal) and check the rendered prompt text.

def test_gender_preference_prompt_says_it_never_excludes_anyone(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    runner = CliRunner()
    answers = "\n".join([
        "My sublet", "East Village", "room",
        "2026-08-18", "2026-09-08", "2200", "y", "1", "none", "",
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert "never exclude" in result.output.lower()


# --- Task 4: the optional price check in `init` -----------------------------
# Typing a price directly (as every test above does) must remain completely
# unaffected — the tests above passing unchanged is itself part of the proof.
# The new branch only opens when the price prompt is left blank.

PLACE = Place(neighborhood="East Village", unit_type="room", bedrooms=1)


def test_suggested_nightly_price_is_the_median_in_comps_mode():
    comp_set = CompSet(comps=[], median=71.5, low=60.0, high=90.0, count=5,
                       dropped=0, thin=False)
    result = PricingResult(mode="comps", place=PLACE, nights=22, comp_set=comp_set)
    assert suggested_nightly_price(result) == 71.5


def test_suggested_nightly_price_is_the_midpoint_in_estimate_mode():
    result = PricingResult(mode="estimate", place=PLACE, nights=22,
                           estimate_low=60.0, estimate_high=90.0)
    assert suggested_nightly_price(result) == 75.0


def test_suggested_nightly_price_is_none_when_nothing_is_computable():
    result = PricingResult(mode="estimate", place=PLACE, nights=22)
    assert suggested_nightly_price(result) is None
    empty_comps = PricingResult(mode="comps", place=PLACE, nights=22,
                                comp_set=CompSet())
    assert suggested_nightly_price(empty_comps) is None


def test_leaving_the_price_blank_and_declining_the_check_falls_back_to_the_manual_prompt(
        tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    runner = CliRunner()
    answers = "\n".join([
        "My sublet", "East Village", "room", "2026-08-18", "2026-09-08",
        "",       # leave price blank
        "n",      # decline the price check
        "2200",   # manual price, same as the old flow
        "y", "1", "none", "",
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output

    conn = connect(tmp_path / "sublease.db")
    profile = ProfileRepo(conn).list()[0]
    assert profile.price.total == 2200.0


def test_accepting_the_price_check_and_using_the_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    provider = FakeProvider(responses={"EstimateResult:East Village": {
        "low": 60.0, "high": 90.0, "note": None}})
    monkeypatch.setattr("sublease.cli.main.get_provider",
                        lambda name, model=None, **kw: provider)

    runner = CliRunner()
    answers = "\n".join([
        "My sublet", "East Village", "room", "2026-08-18", "2026-09-08",
        "",       # leave price blank
        "y",      # accept the price check
        "y",      # use the suggested figure
        "y", "1", "none", "",
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert "ESTIMATE" in result.output   # visibly labelled, not presented as a real comp

    conn = connect(tmp_path / "sublease.db")
    profile = ProfileRepo(conn).list()[0]
    nights = 22   # Aug 18 - Sep 8 inclusive
    assert profile.price.total == pytest.approx(75.0 * nights)   # midpoint of 60-90


def test_accepting_the_check_but_declining_the_suggestion_still_asks_manually(
        tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    provider = FakeProvider(responses={"EstimateResult:East Village": {
        "low": 60.0, "high": 90.0, "note": None}})
    monkeypatch.setattr("sublease.cli.main.get_provider",
                        lambda name, model=None, **kw: provider)

    runner = CliRunner()
    answers = "\n".join([
        "My sublet", "East Village", "room", "2026-08-18", "2026-09-08",
        "",       # leave price blank
        "y",      # accept the price check
        "n",      # decline the suggested figure
        "2500",   # enter their own
        "y", "1", "none", "",
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output

    conn = connect(tmp_path / "sublease.db")
    profile = ProfileRepo(conn).list()[0]
    assert profile.price.total == 2500.0


def test_an_unavailable_provider_during_the_price_check_never_blocks_init(
        tmp_path, monkeypatch):
    """`init` must complete even when the price check can't reach a model —
    it says so and falls through to the plain manual prompt, exactly like a
    decline."""
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))

    def boom(name, model=None, **kw):
        raise RuntimeError("no api key configured")

    monkeypatch.setattr("sublease.cli.main.get_provider", boom)

    runner = CliRunner()
    answers = "\n".join([
        "My sublet", "East Village", "room", "2026-08-18", "2026-09-08",
        "",       # leave price blank
        "y",      # accept the offer to check
        "2200",   # provider unavailable -> falls back to the manual prompt
        "y", "1", "none", "",
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert "unavailable" in result.output.lower()

    conn = connect(tmp_path / "sublease.db")
    profile = ProfileRepo(conn).list()[0]
    assert profile.price.total == 2200.0
