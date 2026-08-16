from sublease.cli.doctor import Check, run_checks
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
