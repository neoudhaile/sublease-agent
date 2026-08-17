"""End-to-end tests for `sublease price`, driven through the real CLI with
`CliRunner` and a `FakeProvider` swapped in for `get_provider` — no network,
same pattern `test_cli_doctor.py`'s end-to-end test uses."""
from datetime import date

from typer.testing import CliRunner

from sublease.cli.main import app
from sublease.profile.models import (
    Constraints, Place, Price, Profile, Templates, Window,
)
from sublease.store.db import connect, migrate
from sublease.store.repositories import OfferRepo, PostRepo, ProfileRepo
from tests.fakes import FakeProvider


def a_profile():
    return Profile(
        name="East Village room", place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200), constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="Room."))


def test_price_command_reports_no_profile_before_init(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["price"])
    assert "sublease init" in result.output


def test_price_command_shows_a_labelled_estimate_when_no_comps_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    conn = connect(tmp_path / "sublease.db")
    migrate(conn)
    ProfileRepo(conn).save(a_profile())

    provider = FakeProvider(responses={"EstimateResult:East Village": {
        "low": 55.0, "high": 85.0, "note": None}})
    monkeypatch.setattr("sublease.cli.main.get_provider",
                        lambda name, model=None, **kw: provider)

    runner = CliRunner()
    result = runner.invoke(app, ["price"])
    assert result.exit_code == 0, result.output
    assert "ESTIMATE" in result.output
    assert "$55" in result.output and "$85" in result.output


def test_price_command_shows_real_comps_when_offers_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    conn = connect(tmp_path / "sublease.db")
    migrate(conn)
    ProfileRepo(conn).save(a_profile())
    PostRepo(conn).upsert_many([{"id": "fbpost:1", "text": "$70/night room in EV"}])
    OfferRepo(conn).save_many([{
        "post_id": "fbpost:1", "price_amount": 70, "price_unit": "night",
        "nightly_price": 70.0, "currency": "USD", "neighborhood": "East Village",
        "unit_type": "room", "bedrooms": 2, "bath": "shared", "furnished": True,
        "start_date": "2026-08-15", "end_date": "2026-09-05", "model": "fake",
        "error": None,
    }])

    provider = FakeProvider(responses={"NeighborhoodBatch:East Village": {
        "results": [{"neighborhood": "East Village", "relation": "same"}]}})
    monkeypatch.setattr("sublease.cli.main.get_provider",
                        lambda name, model=None, **kw: provider)

    runner = CliRunner()
    result = runner.invoke(app, ["price"])
    assert result.exit_code == 0, result.output
    assert "ESTIMATE" not in result.output
    assert "comparable" in result.output
    assert "$70" in result.output


def test_price_command_fails_cleanly_when_provider_construction_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    conn = connect(tmp_path / "sublease.db")
    migrate(conn)
    ProfileRepo(conn).save(a_profile())

    runner = CliRunner()
    result = runner.invoke(app, ["price", "--provider", "bogus-provider"])
    assert result.exit_code == 1
    assert "unknown provider" in result.output


def test_price_appears_in_the_top_level_help():
    result = CliRunner().invoke(app, ["--help"])
    assert "price" in result.output
