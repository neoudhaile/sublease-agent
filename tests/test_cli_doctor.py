from typer.testing import CliRunner

from sublease.cli.doctor import Check, run_checks
from sublease.cli.main import app
from sublease.llm.base import ProviderHealth
from sublease.store.db import connect, migrate
from tests.fakes import FakeProvider


class UnhealthyProvider(FakeProvider):
    def health(self):
        return ProviderHealth(ok=False, detail="ANTHROPIC_API_KEY is not set")


def names(checks):
    return [c.name for c in checks]


def by_name(checks, name):
    return next(c for c in checks if c.name == name)


def test_all_four_checks_are_reported(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    checks = run_checks(conn=conn, provider=FakeProvider(), which=lambda _: "/bin/forage")
    assert names(checks) == ["database", "llm provider", "forage", "profile"]


def test_a_healthy_setup_passes_every_check(tmp_path):
    from sublease.profile.models import (
        Constraints, Place, Price, Profile, Templates, Window,
    )
    from datetime import date
    from sublease.store.repositories import ProfileRepo

    conn = connect(tmp_path / "t.db")
    migrate(conn)
    ProfileRepo(conn).save(Profile(
        name="p", place=Place(neighborhood="EV"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=1), constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="x")))
    checks = run_checks(conn=conn, provider=FakeProvider(), which=lambda _: "/bin/forage")
    assert all(c.ok for c in checks)


def test_an_unhealthy_provider_is_reported_without_raising(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    checks = run_checks(conn=conn, provider=UnhealthyProvider(),
                        which=lambda _: "/bin/forage")
    provider_check = by_name(checks, "llm provider")
    assert provider_check.ok is False
    assert "ANTHROPIC_API_KEY" in provider_check.detail


def test_a_missing_forage_binary_is_reported(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    check = by_name(run_checks(conn=conn, provider=FakeProvider(), which=lambda _: None),
                    "forage")
    assert check.ok is False
    assert "not installed" in check.detail


def test_an_unmigrated_database_is_reported(tmp_path):
    conn = connect(tmp_path / "t.db")   # deliberately not migrated
    check = by_name(run_checks(conn=conn, provider=FakeProvider(),
                               which=lambda _: "/bin/forage"), "database")
    assert check.ok is False


def test_no_profile_is_reported_with_the_fix(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    check = by_name(run_checks(conn=conn, provider=FakeProvider(),
                               which=lambda _: "/bin/forage"), "profile")
    assert check.ok is False
    assert "sublease init" in check.detail


def test_one_failing_check_never_hides_the_others(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    checks = run_checks(conn=conn, provider=UnhealthyProvider(), which=lambda _: None)
    assert len(checks) == 4


def test_check_is_a_value_object():
    c = Check(name="x", ok=True, detail="fine")
    assert (c.name, c.ok, c.detail) == ("x", True, "fine")


# --- Fix round 1 -----------------------------------------------------------
# Finding 4: when provider construction fails, the real reason must reach
# the `Check` detail the user is actually reading, not just a printed
# warning that scrolls past.

def test_a_failed_provider_construction_shows_its_reason_in_the_check(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    checks = run_checks(conn=conn, provider=None,
                        provider_error="unknown provider 'bogus'; expected one of ...",
                        which=lambda _: "/bin/forage")
    check = by_name(checks, "llm provider")
    assert check.ok is False
    assert "bogus" in check.detail


def test_doctor_command_surfaces_the_real_provider_failure_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--provider", "bogus-provider"])
    assert "unknown provider" in result.output
    assert "bogus-provider" in result.output
    assert "no provider configured" not in result.output


# --- Fix wave 2026-08-15 ----------------------------------------------------
# Finding 3: `doctor`'s provider check used to call `provider.health()`
# unconditionally, which for the Anthropic and OpenAI providers issues a
# real (billable) completion request on every run. The default check must
# now be the cheap, offline `ready()` check; only `--probe` should reach for
# `health()`.

class SpyProvider(FakeProvider):
    """Records which of ready()/health() doctor actually called, so the
    default-vs-probe wiring can be asserted rather than assumed."""

    def __init__(self):
        super().__init__()
        self.ready_calls = 0
        self.health_calls = 0

    def ready(self):
        self.ready_calls += 1
        return ProviderHealth(ok=True, detail="spy ready; connectivity not verified")

    def health(self):
        self.health_calls += 1
        return ProviderHealth(ok=True, detail="spy reachable")


def test_the_default_provider_check_never_makes_a_real_request(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    spy = SpyProvider()
    checks = run_checks(conn=conn, provider=spy, which=lambda _: "/bin/forage")
    assert spy.ready_calls == 1
    assert spy.health_calls == 0
    check = by_name(checks, "llm provider")
    assert check.ok is True
    assert "connectivity not verified" in check.detail


def test_probe_true_makes_the_real_request_instead(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    spy = SpyProvider()
    checks = run_checks(conn=conn, provider=spy, which=lambda _: "/bin/forage",
                        probe=True)
    assert spy.ready_calls == 0
    assert spy.health_calls == 1
    check = by_name(checks, "llm provider")
    assert check.detail == "spy reachable"


def test_a_failing_provider_construction_is_still_reported_with_no_provider_to_probe(tmp_path):
    """provider=None (construction failed) must never crash `ready()`/`health()`
    lookups — the "llm provider" check still reports the construction error,
    with or without --probe."""
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    checks = run_checks(conn=conn, provider=None, provider_error="boom",
                        which=lambda _: "/bin/forage", probe=True)
    check = by_name(checks, "llm provider")
    assert check.ok is False
    assert check.detail == "boom"


def test_doctor_command_default_output_says_connectivity_was_not_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["doctor"])
    assert "connectivity was not verified" in result.output.lower()


def test_doctor_probe_help_text_discloses_the_real_request(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--help"])
    assert "--probe" in result.output
    assert "billable" in result.output.lower() or "real" in result.output.lower()
