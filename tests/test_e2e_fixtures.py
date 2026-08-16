"""The whole pipeline over fixtures/posts.json, with a canned provider.

Deliberately deterministic: the LLM is faked, so this asserts the engine's
behaviour rather than any model's. Expected values were derived by hand from
the window Aug 18 - Sep 8 2026 (22 days) and from reading match/window.py,
match/tiering.py, match/coverage.py, and match/dedupe.py directly.

Marker note: the collision the M1 plan anticipated here — "fbpost:1" matching
inside "fbpost:10" — was already fixed in tests/fakes.py during Task 8 (the
LONGEST matching marker wins). Plain post-id markers are used below for the
extraction pass and that fix is sufficient for it.

A second, different collision shows up in this test that the plan didn't
anticipate: the extraction prompt and the enrichment prompt for the SAME post
both contain the bare post id verbatim, and nothing else in either prompt
distinguishes which pass is asking. A bare marker can't tell them apart, and
(unlike the length collision) there is no "longest wins" way out of it, since
they are the identical string. Concretely, a couple's post ("Overlap Owen")
and an open-ended seeker's post ("Outside Otis") need enrichment payloads
that differ from the extraction payload for the same id — if the enrichment
call accidentally resolved to the extraction marker, EnrichmentBatch would
silently validate it anyway (its fields all have defaults), just with the
WRONG defaults, and the couple/multi-room assertions below would fail
silently rather than error loudly. tests/fakes.py was extended with an
opt-in schema-qualified marker (f"{schema.__name__}:rest", e.g.
"EnrichmentBatch:fbpost:7") for exactly this: it matches only calls made
with that schema, so the enrichment pass resolves unambiguously to the
enrichment payload even though the extraction prompt for the same id is
sitting right next to it in every batch. See tests/fakes.py's docstring.
"""
from datetime import date
from pathlib import Path

import pytest

from sublease.pipeline import run_pipeline
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)
from sublease.sources.fixtures import FixtureSource
from sublease.store.db import connect, migrate
from sublease.store.repositories import CandidateRepo, ProfileRepo
from tests.fakes import FakeProvider

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "posts.json"
TODAY = date(2026, 8, 11)
CFG = SourceConfig(slug="test", name="Fixture Group", method="fixtures")

# What a correct model returns for each fixture post that reaches the model.
EXTRACTIONS = {
    "fbpost:1": ("Exact Emma", True, "2026-08-18", "2026-09-08"),
    "fbpost:2": ("Inside Ivan", True, "2026-08-20", "2026-09-01"),
    "fbpost:3": ("Fuzzy Fiona", True, "2026-08-18", "2026-08-31"),
    "fbpost:4": ("Labor-Day Lee", True, "2026-08-25", "2026-09-07"),
    "fbpost:5": ("Offering Olga", False, None, None),
    "fbpost:7": ("Overlap Owen", True, "2026-08-01", "2026-09-01"),
    "fbpost:8": ("Numeric Nia", True, "2026-08-30", "2026-09-08"),
    "fbpost:9": ("Open-End Omar", True, "2026-08-22", None),
    "fbpost:10": ("Outside Otis", True, "2026-09-15", "2026-10-30"),
}
# fbpost:6 has no date tokens, so it is prefiltered and never reaches the model.

ENRICHMENTS = {
    "fbpost:7": {"people_in_one_room": 2, "group_size": 2},   # a couple
    "fbpost:10": {"people_in_one_room": 1, "wants_multiple_rooms": True},
}


def canned_provider():
    responses = {}
    for pid, (_name, seeking, start, end) in EXTRACTIONS.items():
        responses[pid] = {"results": [{
            "id": pid, "is_seeking": seeking, "start_date": start,
            "end_date": end, "date_text": None, "budget": None,
            "confidence": "high"}]}
    for pid in EXTRACTIONS:
        extra = ENRICHMENTS.get(pid, {})
        responses[f"EnrichmentBatch:{pid}"] = {"results": [{
            "id": pid,
            "people_in_one_room": extra.get("people_in_one_room", 1),
            "wants_multiple_rooms": extra.get("wants_multiple_rooms", False),
            "gender": extra.get("gender"),
            "group_size": extra.get("group_size", 1)}]}
    return FakeProvider(responses=responses)


@pytest.fixture
def setup(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    profile = ProfileRepo(conn).save(Profile(
        name="East Village room",
        place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(
            outreach_message="Hi {first_name}, saw your post in {group}",
            listing_post="Room available."),
        sources=[CFG]))
    return conn, profile


def run(setup):
    conn, profile = setup
    report = run_pipeline(conn, profile, canned_provider(), TODAY,
                          sources={CFG: FixtureSource(FIXTURES)})
    return conn, profile, report


def test_all_ten_fixture_posts_are_ingested(setup):
    _conn, _profile, report = run(setup)
    assert report.scraped == 10
    assert report.new_posts == 10


def test_the_undated_post_never_reaches_the_model(setup):
    conn, _profile, _report = run(setup)
    row = conn.execute(
        "SELECT model, is_seeking FROM extraction WHERE post_id='fbpost:6'").fetchone()
    assert row["model"] is None
    assert row["is_seeking"] == 0


def test_seven_candidates_survive_the_window_filter(setup):
    _conn, _profile, report = run(setup)
    assert report.candidates == 7


def test_the_offerer_is_excluded(setup):
    conn, profile, _ = run(setup)
    names = {c["author_name"] for c in CandidateRepo(conn).list(profile.id)}
    assert "Offering Olga" not in names


def test_the_post_with_no_dates_is_excluded(setup):
    conn, profile, _ = run(setup)
    names = {c["author_name"] for c in CandidateRepo(conn).list(profile.id)}
    assert "No-Dates Ned" not in names


def test_the_candidate_outside_the_window_is_excluded(setup):
    conn, profile, _ = run(setup)
    names = {c["author_name"] for c in CandidateRepo(conn).list(profile.id)}
    assert "Outside Otis" not in names


def test_the_exact_match_is_tier_a_and_ranked_first(setup):
    conn, profile, _ = run(setup)
    rows = CandidateRepo(conn).list(profile.id)
    assert rows[0]["author_name"] == "Exact Emma"
    assert rows[0]["tier"] == "A"
    assert rows[0]["fit"] == "full-window"
    assert rows[0]["days_covered"] == 22


def test_the_couple_is_the_only_tier_d(setup):
    conn, profile, _ = run(setup)
    rows = CandidateRepo(conn).list(profile.id)
    d_tier = [r["author_name"] for r in rows if r["tier"] == "D"]
    assert d_tier == ["Overlap Owen"]


def test_the_open_ended_seeker_runs_to_the_window_end(setup):
    conn, profile, _ = run(setup)
    omar = next(c for c in CandidateRepo(conn).list(profile.id)
                if c["author_name"] == "Open-End Omar")
    assert omar["days_covered"] == 18
    assert omar["wants_end"] is None


def test_every_candidate_gets_a_rendered_draft(setup):
    conn, profile, _ = run(setup)
    for row in CandidateRepo(conn).list(profile.id):
        assert row["draft"]
        assert "{" not in row["draft"]


def test_tiers_are_ordered_a_then_b_then_c_then_d(setup):
    conn, profile, _ = run(setup)
    tiers = [r["tier"] for r in CandidateRepo(conn).list(profile.id)]
    assert tiers == sorted(tiers, key=lambda t: "ABCD".index(t))


def test_coverage_finds_a_combination_tiling_the_whole_window(setup):
    from sublease.match.coverage import coverage
    from sublease.match.ranking import rank
    from sublease.store.repositories import (
        EnrichmentRepo, ExtractionRepo, PostRepo,
    )
    conn, profile, _ = run(setup)
    ranked = rank({p["id"]: p for p in PostRepo(conn).get_all()},
                  ExtractionRepo(conn).get_all(),
                  EnrichmentRepo(conn).by_post_id(), profile)
    plan = coverage(ranked, profile.window.start, profile.window.end, max_split=3)
    # Not asserting WHICH candidates were picked: Exact Emma alone covers the
    # full 22-day window, so the sweep's fewest-intervals guarantee means
    # it will pick her alone here regardless of tie-break details elsewhere
    # in the candidate list. What matters, and what stays true under any
    # correct implementation, is that full coverage is found at all.
    assert plan.combination_days == 22


def test_a_second_run_adds_no_new_candidates(setup):
    conn, profile = setup
    provider = canned_provider()
    source = FixtureSource(FIXTURES)
    run_pipeline(conn, profile, provider, TODAY, sources={CFG: source})
    second = run_pipeline(conn, profile, provider, TODAY, sources={CFG: source})
    assert second.new_candidates == 0
    assert second.extracted == 0
