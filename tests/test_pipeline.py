from datetime import date
import pytest
from sublease.errors import SourceError
from sublease.pipeline import RunReport, run_pipeline
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)
from sublease.store.db import connect, migrate
from sublease.store.repositories import CandidateRepo, PostRepo, ProfileRepo
from tests.fakes import FakeProvider

TODAY = date(2026, 8, 11)
CFG = SourceConfig(slug="test", name="Fixture Group", method="fixtures")


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


@pytest.fixture
def profile(conn):
    return ProfileRepo(conn).save(Profile(
        name="East Village room",
        place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="Room."),
        sources=[CFG],
    ))


class StubSource:
    name = "stub"

    def __init__(self, posts, error=None):
        self.posts, self.error = posts, error

    def fetch(self, cfg, since, limit):
        if self.error:
            raise self.error
        return self.posts


def raw(pid, name, text="ISO a room Aug 18 - Sep 8"):
    return {"id": pid, "source": "stub", "url": f"https://fb.com/{pid}",
            "group_name": "Fixture Group", "author_name": name,
            "author_url": f"https://fb.com/{name}", "posted_at": "2026-08-10",
            "text": text}


def provider_for(*post_ids):
    return FakeProvider(responses={
        pid: {"results": [{"id": pid, "is_seeking": True,
                           "start_date": "2026-08-18", "end_date": "2026-09-08",
                           "date_text": "Aug 18 - Sep 8", "budget": None,
                           "confidence": "high"}]}
        for pid in post_ids
    } | {
        f"ENRICH-{pid}": {"results": [{"id": pid, "people_in_one_room": 1,
                                       "wants_multiple_rooms": False,
                                       "gender": None, "group_size": 1}]}
        for pid in post_ids
    })


def test_a_full_run_produces_candidates(conn, profile):
    source = StubSource([raw("fbpost:1", "Emma")])
    report = run_pipeline(conn, profile, provider_for("fbpost:1"), TODAY,
                          sources={CFG: source})
    assert report.new_posts == 1
    assert report.candidates == 1
    assert CandidateRepo(conn).list(profile.id)[0]["tier"] == "A"


def test_the_report_counts_every_stage(conn, profile):
    source = StubSource([raw("fbpost:1", "Emma")])
    report = run_pipeline(conn, profile, provider_for("fbpost:1"), TODAY,
                          sources={CFG: source})
    assert isinstance(report, RunReport)
    assert report.scraped == 1
    assert report.extracted == 1
    assert report.new_candidates == 1


def test_a_second_run_re_extracts_nothing(conn, profile):
    source = StubSource([raw("fbpost:1", "Emma")])
    provider = provider_for("fbpost:1")
    run_pipeline(conn, profile, provider, TODAY, sources={CFG: source})
    calls_after_first = len(provider.calls)
    second = run_pipeline(conn, profile, provider, TODAY, sources={CFG: source})
    assert len(provider.calls) == calls_after_first
    assert second.extracted == 0
    assert second.new_candidates == 0


def test_a_failing_source_is_recorded_and_the_run_continues(conn, profile):
    good = SourceConfig(slug="good", name="Good Group", method="fixtures")
    bad = SourceConfig(slug="bad", name="Bad Group", method="fixtures")
    profile.sources = [good, bad]
    report = run_pipeline(
        conn, profile, provider_for("fbpost:1"), TODAY,
        sources={good: StubSource([raw("fbpost:1", "Emma")]),
                 bad: StubSource([], error=SourceError("session expired"))})
    assert report.new_posts == 1
    assert len(report.source_errors) == 1
    assert "session expired" in report.source_errors[0]


def test_every_source_failing_is_not_fatal(conn, profile):
    report = run_pipeline(
        conn, profile, FakeProvider(), TODAY,
        sources={CFG: StubSource([], error=SourceError("down"))})
    assert report.scraped == 0
    assert report.candidates == 0


def test_dry_run_writes_no_candidates(conn, profile):
    source = StubSource([raw("fbpost:1", "Emma")])
    report = run_pipeline(conn, profile, provider_for("fbpost:1"), TODAY,
                          sources={CFG: source}, dry_run=True)
    assert report.candidates == 1
    assert CandidateRepo(conn).list(profile.id) == []


def test_dry_run_writes_no_posts(conn, profile):
    run_pipeline(conn, profile, provider_for("fbpost:1"), TODAY,
                 sources={CFG: StubSource([raw("fbpost:1", "Emma")])}, dry_run=True)
    assert PostRepo(conn).get_all() == []


def test_dry_run_counts_match_a_real_run_over_the_same_state(conn, profile):
    """A dry-run preview must not report numbers a real run would not produce.

    dry_run writes nothing (asserted elsewhere), so running it first against
    `conn` leaves the database exactly as it started — the real run right
    after it therefore sees the SAME starting state the dry run saw. Each
    pass gets its own StubSource/FakeProvider instances (both are call
    recorders) so neither pass's call history leaks into the other's.
    """
    posts = [raw("fbpost:1", "Emma"), raw("fbpost:2", "Olga")]

    dry_report = run_pipeline(
        conn, profile, provider_for("fbpost:1", "fbpost:2"), TODAY,
        sources={CFG: StubSource(list(posts))}, dry_run=True)

    # Confirm dry_run really left nothing behind before comparing counts.
    assert PostRepo(conn).get_all() == []
    assert CandidateRepo(conn).list(profile.id) == []

    real_report = run_pipeline(
        conn, profile, provider_for("fbpost:1", "fbpost:2"), TODAY,
        sources={CFG: StubSource(list(posts))}, dry_run=False)

    # `scraped` is a pure count of fetched posts, computed before either mode
    # touches the db — identical by construction, included for completeness.
    assert dry_report.scraped == real_report.scraped
    assert dry_report.new_posts == real_report.new_posts
    assert dry_report.extracted == real_report.extracted
    assert dry_report.enriched == real_report.enriched
    assert dry_report.candidates == real_report.candidates
    assert dry_report.new_candidates == real_report.new_candidates

    assert real_report.new_posts == 2
    assert real_report.new_candidates == 2


def test_only_seekers_are_enriched(conn, profile):
    provider = FakeProvider(responses={
        "fbpost:1": {"results": [{"id": "fbpost:1", "is_seeking": False}]},
    })
    report = run_pipeline(conn, profile, provider, TODAY,
                          sources={CFG: StubSource([raw("fbpost:1", "Olga")])})
    assert report.enriched == 0
    assert report.candidates == 0
