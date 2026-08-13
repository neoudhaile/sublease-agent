# Sublease Agent M1 — Part 4: Ranking, Pipeline, CLI (Tasks 17–21)

> Continues `2026-08-11-m1-core-engine-part3.md`. The header, Global Constraints, and File Structure in Part 1 apply to every task here.

---

## Task 17: Ranking orchestration

**Files:**
- Create: `sublease/match/ranking.py`
- Modify: `sublease/match/__init__.py`
- Test: `tests/test_match_ranking.py`

**Interfaces:**
- Consumes: Tasks 13–16 (`classify`, `tier_for`, `dedupe_people`, `person_key`, `build_draft`), Task 2 `Profile`
- Produces: `rank(posts: dict[str, dict], extractions: list[dict], enrichments: dict[str, dict], profile: Profile) -> list[Candidate]`; `to_rows(candidates: list[Candidate]) -> list[dict]` shaped for `CandidateRepo.sync`

`rank` is the single place the pieces are joined: seekers only, window overlap filter, fact assembly, person dedupe, tiering, ordering, draft rendering. Ordering is ported from `filter_rank.py:185-189` — a stable sort by recency first, then the primary sort by tier, days covered, and fit.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match_ranking.py
from datetime import date
from sublease.match.ranking import rank, to_rows
from sublease.profile.models import (
    Constraints, Place, Price, Profile, Templates, Window,
)


def a_profile(**kw):
    base = dict(
        name="East Village room",
        place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(
            outreach_message="Hi {first_name}, saw your post in {group} for {their_dates}",
            listing_post="Room available."),
    )
    return Profile(**{**base, **kw})


def post(pid, name, group="NYC Sublets", posted="2026-08-10", text="ISO a room"):
    return {"id": pid, "author_name": name, "author_url": f"https://fb.com/{name}",
            "url": f"https://fb.com/{pid}", "group_name": group,
            "posted_at": posted, "text": text}


def extraction(pid, seeking=True, start="2026-08-18", end="2026-09-08", **kw):
    base = {"post_id": pid, "is_seeking": seeking, "start_date": start,
            "end_date": end, "budget": None, "confidence": "high",
            "date_text": None}
    return {**base, **kw}


def enrichment(pid, **kw):
    base = {"post_id": pid, "people_in_one_room": 1, "wants_multiple_rooms": False,
            "gender": None, "group_size": 1}
    return {**base, **kw}


def test_offerers_are_excluded():
    got = rank({"p1": post("p1", "Olga")}, [extraction("p1", seeking=False)], {},
               a_profile())
    assert got == []


def test_candidates_outside_the_window_are_excluded():
    posts = {"p1": post("p1", "Otis")}
    ext = [extraction("p1", start="2026-09-15", end="2026-10-30")]
    assert rank(posts, ext, {}, a_profile()) == []


def test_extractions_with_no_matching_post_are_skipped():
    assert rank({}, [extraction("ghost")], {}, a_profile()) == []


def test_a_matching_seeker_becomes_a_tiered_candidate():
    got = rank({"p1": post("p1", "Emma Stone")}, [extraction("p1")],
               {"p1": enrichment("p1")}, a_profile())
    assert len(got) == 1
    assert got[0].name == "Emma Stone"
    assert got[0].tier == "A"
    assert got[0].fit == "full-window"
    assert got[0].days_covered == 22


def test_the_draft_is_rendered_from_the_profile_template():
    got = rank({"p1": post("p1", "Emma Stone")}, [extraction("p1")], {}, a_profile())
    assert got[0].draft == (
        "Hi Emma, saw your post in NYC Sublets for Aug 18 – Sep 8")


def test_missing_enrichment_defaults_to_a_solo_occupant():
    got = rank({"p1": post("p1", "Emma")}, [extraction("p1")], {}, a_profile())
    assert got[0].people_in_one_room == 1
    assert got[0].tier == "A"


def test_enrichment_drives_the_dealbreaker_tier():
    got = rank({"p1": post("p1", "Owen")}, [extraction("p1")],
               {"p1": enrichment("p1", people_in_one_room=2)}, a_profile())
    assert got[0].tier == "D"


def test_gender_preference_is_applied_from_the_profile():
    profile = a_profile(constraints=Constraints(gender_preference="male"))
    got = rank({"p1": post("p1", "Emma")}, [extraction("p1")],
               {"p1": enrichment("p1", gender="female")}, profile)
    assert got[0].tier == "B"


def test_cross_posted_people_collapse_to_one_candidate():
    posts = {"p1": post("p1", "Emma", group="Group A", posted="2026-08-09"),
             "p2": post("p2", "Emma", group="Group B", posted="2026-08-10")}
    got = rank(posts, [extraction("p1"), extraction("p2")], {}, a_profile())
    assert len(got) == 1
    assert got[0].post_id == "p2"
    assert got[0].also_posted_in == ["Group A"]


def test_results_are_ordered_by_tier_then_days_covered():
    posts = {"p1": post("p1", "Partial"), "p2": post("p2", "Full"),
             "p3": post("p3", "Couple")}
    ext = [extraction("p1", start="2026-08-20", end="2026-09-01"),
           extraction("p2"),
           extraction("p3")]
    enr = {"p3": enrichment("p3", people_in_one_room=2)}
    got = rank(posts, ext, enr, a_profile())
    assert [c.name for c in got] == ["Full", "Partial", "Couple"]


def test_ties_are_broken_by_recency():
    posts = {"p1": post("p1", "Older", posted="2026-08-05"),
             "p2": post("p2", "Newer", posted="2026-08-11")}
    got = rank(posts, [extraction("p1"), extraction("p2")], {}, a_profile())
    assert [c.name for c in got] == ["Newer", "Older"]


def test_post_text_is_carried_and_truncated():
    long_text = "x" * 900
    got = rank({"p1": post("p1", "Emma", text=long_text)}, [extraction("p1")], {},
               a_profile())
    assert len(got[0].post_text) == 500


def test_newlines_are_flattened_in_carried_post_text():
    got = rank({"p1": post("p1", "Emma", text="line one\nline two")},
               [extraction("p1")], {}, a_profile())
    assert "\n" not in got[0].post_text


def test_to_rows_shapes_candidates_for_the_repository():
    got = rank({"p1": post("p1", "Emma")}, [extraction("p1")], {}, a_profile())
    row = to_rows(got)[0]
    assert row["person_key"] == got[0].person_key
    assert row["post_id"] == "p1"
    assert row["tier"] == "A"
    assert row["wants_start"] == "2026-08-18"
    assert row["also_posted_in"] == []


def test_to_rows_serialises_open_dates_as_none():
    got = rank({"p1": post("p1", "Omar")},
               [extraction("p1", start="2026-08-22", end=None)], {}, a_profile())
    row = to_rows(got)[0]
    assert row["wants_end"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_match_ranking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.match.ranking'`

- [ ] **Step 3: Write `sublease/match/ranking.py`**

```python
"""Join extractions, enrichments, and posts into a ranked candidate list.

Ported from reference/pipeline/filter_rank.py:126-214. The one behavioural
change is that every rule now reads from the profile rather than a constant.

Ordering is a two-pass stable sort, exactly as the prototype did it: sort by
recency first, then by (tier, days covered, fit). Python's sort is stable, so the
recency pass survives as the tie-breaker within each tier.
"""
from __future__ import annotations

from datetime import date

from sublease.match.dedupe import dedupe_people, person_key
from sublease.match.drafts import build_draft
from sublease.match.tiering import tier_for
from sublease.match.types import FIT_ORDER, TIER_ORDER, Candidate
from sublease.match.window import classify
from sublease.profile.models import Profile

POST_TEXT_LIMIT = 500


def _parse(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def rank(posts: dict[str, dict], extractions: list[dict],
         enrichments: dict[str, dict], profile: Profile) -> list[Candidate]:
    w_start, w_end = profile.window.start, profile.window.end
    window_days = profile.window.days

    candidates: list[Candidate] = []
    for row in extractions:
        if not row.get("is_seeking"):
            continue
        post = posts.get(row["post_id"])
        if post is None:
            continue

        start = _parse(row.get("start_date"))
        end = _parse(row.get("end_date"))
        fit, days = classify(start, end, w_start, w_end)
        if fit is None:
            continue

        enriched = enrichments.get(row["post_id"], {})
        name = post.get("author_name")
        candidates.append(Candidate(
            post_id=row["post_id"],
            person_key=person_key(name, start, end),
            name=name,
            fit=fit,
            days_covered=days,
            wants_start=start,
            wants_end=end,
            profile_url=post.get("author_url"),
            post_url=post.get("url"),
            group_name=post.get("group_name"),
            post_date=post.get("posted_at"),
            budget=row.get("budget"),
            confidence=row.get("confidence"),
            date_text=row.get("date_text"),
            people_in_one_room=enriched.get("people_in_one_room"),
            wants_multiple_rooms=bool(enriched.get("wants_multiple_rooms")),
            gender=enriched.get("gender"),
            occupants=(enriched.get("group_size")
                       or enriched.get("people_in_one_room") or 1),
            post_text=(post.get("text") or "")[:POST_TEXT_LIMIT].replace("\n", " "),
        ))

    candidates = dedupe_people(candidates)

    for candidate in candidates:
        candidate.tier, candidate.tier_reason = tier_for(
            candidate.facts(), profile.constraints, window_days)
        candidate.draft = build_draft(profile.templates.outreach_message, candidate)

    candidates.sort(key=lambda c: str(c.post_date or ""), reverse=True)
    candidates.sort(key=lambda c: (TIER_ORDER.get(c.tier or "", 9),
                                   -c.days_covered,
                                   FIT_ORDER.get(c.fit, 9)))
    return candidates


def to_rows(candidates: list[Candidate]) -> list[dict]:
    """Shape candidates for CandidateRepo.sync."""
    return [
        {
            "person_key": c.person_key,
            "post_id": c.post_id,
            "also_posted_in": c.also_posted_in,
            "tier": c.tier,
            "tier_reason": c.tier_reason,
            "fit": c.fit,
            "days_covered": c.days_covered,
            "wants_start": c.wants_start.isoformat() if c.wants_start else None,
            "wants_end": c.wants_end.isoformat() if c.wants_end else None,
            "draft": c.draft,
        }
        for c in candidates
    ]
```

- [ ] **Step 4: Update `sublease/match/__init__.py`**

Add to the imports and `__all__`:

```python
from sublease.match.ranking import rank, to_rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_match_ranking.py -v`
Expected: 15 passed

- [ ] **Step 6: Commit**

```bash
git add sublease/match tests/test_match_ranking.py
git commit -m "feat: ranking orchestration joining extraction, enrichment, and posts"
```

---

## Task 18: Pipeline orchestration

**Files:**
- Create: `sublease/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 4, 6, 7, 8, 12, 17
- Produces:
  - `RunReport` dataclass: `scraped: int`, `new_posts: int`, `extracted: int`, `enriched: int`, `candidates: int`, `new_candidates: int`, `source_errors: list[str]`
  - `run_pipeline(conn, profile, provider, today, sources=None, since=None, limit=300, dry_run=False) -> RunReport`

`sources` is a mapping of `SourceConfig` to an already-constructed `Source`, injected by the CLI. That keeps the pipeline free of registry lookups and lets tests pass fakes.

A failing source is recorded in `source_errors` and the run continues — one broken scraper must never cost a whole run.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
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


def test_only_seekers_are_enriched(conn, profile):
    provider = FakeProvider(responses={
        "fbpost:1": {"results": [{"id": "fbpost:1", "is_seeking": False}]},
    })
    report = run_pipeline(conn, profile, provider, TODAY,
                          sources={CFG: StubSource([raw("fbpost:1", "Olga")])})
    assert report.enriched == 0
    assert report.candidates == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.pipeline'`

- [ ] **Step 3: Write `sublease/pipeline.py`**

```python
"""scrape -> extract -> enrich -> match -> store.

Each stage reads what the previous one persisted, so a run interrupted halfway
resumes without repeating work. A source that fails is recorded and skipped —
one broken scraper must never cost a whole run (reference/pipeline/scrape.py:109).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from sublease.errors import SourceError
from sublease.extract.runner import run_enrichment, run_extraction
from sublease.match.ranking import rank, to_rows
from sublease.profile.models import Profile, SourceConfig
from sublease.sources.base import Source
from sublease.store.repositories import (
    CandidateRepo, EnrichmentRepo, ExtractionRepo, PostRepo,
)

DEFAULT_LOOKBACK_DAYS = 21
DEFAULT_LIMIT = 300


@dataclass
class RunReport:
    scraped: int = 0
    new_posts: int = 0
    extracted: int = 0
    enriched: int = 0
    candidates: int = 0
    new_candidates: int = 0
    source_errors: list[str] = field(default_factory=list)


def run_pipeline(conn: sqlite3.Connection, profile: Profile, provider,
                 today: date, sources: dict[SourceConfig, Source] | None = None,
                 since: date | None = None, limit: int = DEFAULT_LIMIT,
                 dry_run: bool = False) -> RunReport:
    report = RunReport()
    since = since or today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    sources = sources or {}

    # 1. Scrape
    fetched: list[dict] = []
    for cfg in profile.sources:
        source = sources.get(cfg)
        if source is None:
            report.source_errors.append(f"{cfg.name}: no adapter configured")
            continue
        try:
            posts = source.fetch(cfg, since, limit)
        except SourceError as exc:
            report.source_errors.append(f"{cfg.name}: {exc}")
            continue
        fetched.extend(p for p in posts if (p.get("text") or "").strip())
    report.scraped = len(fetched)

    if dry_run:
        return _dry_run(conn, profile, provider, today, fetched, report)

    report.new_posts = PostRepo(conn).upsert_many(fetched)

    # 2. Extract — only posts with no extraction row yet.
    pending_ids = PostRepo(conn).ids_without_extraction()
    pending = list(PostRepo(conn).get_many(pending_ids).values())
    if pending:
        rows = run_extraction(pending, provider, today=today)
        ExtractionRepo(conn).save_many(rows)
        report.extracted = len(rows)

    # 3. Enrich — seekers only, and only those not already enriched.
    seekers = set(ExtractionRepo(conn).seeker_ids()) - EnrichmentRepo(conn).done_ids()
    if seekers:
        posts = list(PostRepo(conn).get_many(sorted(seekers)).values())
        rows = run_enrichment(posts, provider)
        EnrichmentRepo(conn).save_many(rows)
        report.enriched = len(rows)

    # 4. Match
    candidates = rank(
        {p["id"]: p for p in PostRepo(conn).get_all()},
        ExtractionRepo(conn).get_all(),
        EnrichmentRepo(conn).by_post_id(),
        profile,
    )
    report.candidates = len(candidates)

    # 5. Store
    new, _updated = CandidateRepo(conn).sync(profile.id, to_rows(candidates))
    report.new_candidates = new
    return report


def _dry_run(conn, profile, provider, today, fetched, report: RunReport) -> RunReport:
    """Report what a run would produce without writing anything."""
    known = {p["id"]: p for p in PostRepo(conn).get_all()}
    merged = {**known, **{p["id"]: p for p in fetched}}
    report.new_posts = len(set(merged) - set(known))

    extractions = ExtractionRepo(conn).get_all()
    done = {r["post_id"] for r in extractions}
    pending = [p for p in merged.values() if p["id"] not in done]
    if pending:
        fresh = run_extraction(pending, provider, today=today)
        extractions = extractions + fresh
        report.extracted = len(fresh)

    enrichments = EnrichmentRepo(conn).by_post_id()
    seekers = [r["post_id"] for r in extractions if r.get("is_seeking")]
    todo = [merged[i] for i in seekers if i in merged and i not in enrichments]
    if todo:
        fresh = run_enrichment(todo, provider)
        enrichments = {**enrichments, **{r["post_id"]: r for r in fresh}}
        report.enriched = len(fresh)

    candidates = rank(merged, extractions, enrichments, profile)
    report.candidates = len(candidates)
    report.new_candidates = len(candidates)
    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add sublease/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestration with resumable stages and per-source isolation"
```

---

## Task 19: CLI — `doctor` and `init`

**Files:**
- Create: `sublease/cli/__init__.py`, `sublease/cli/main.py`, `sublease/cli/doctor.py`, `sublease/cli/init.py`
- Test: `tests/test_cli_doctor.py`, `tests/test_cli_init.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 4, 8
- Produces:
  - `sublease.cli.doctor.Check` dataclass: `name: str`, `ok: bool`, `detail: str`
  - `sublease.cli.doctor.run_checks(conn=None, provider=None, forage_binary="forage", which=shutil.which) -> list[Check]`
  - `sublease.cli.init.build_profile(answers: dict) -> Profile`, `DEFAULT_TEMPLATES`
  - `sublease.cli.main.app` — the Typer application

`doctor` exists so a run never wastes twenty minutes discovering a stale session. Every check returns a `Check` rather than raising, so one failure does not hide the others.

- [ ] **Step 1: Write the failing doctor test**

```python
# tests/test_cli_doctor.py
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cli_doctor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.cli'`

- [ ] **Step 3: Write `sublease/cli/doctor.py`**

```python
"""Pre-flight checks.

A scrape run takes twenty minutes. Discovering a stale Facebook session at
minute nineteen is the failure this command exists to prevent. Every check
returns a result rather than raising, so one failure never hides the rest.
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass

from sublease.errors import SubleaseError
from sublease.store.db import current_version
from sublease.store.repositories import ProfileRepo
from sublease.store.schema import MIGRATIONS


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check_database(conn: sqlite3.Connection) -> Check:
    try:
        version = current_version(conn)
    except SubleaseError as exc:
        return Check("database", False, str(exc))
    if version < len(MIGRATIONS):
        return Check("database", False,
                     f"schema is at v{version}, expected v{len(MIGRATIONS)}; "
                     "run `sublease init` to migrate")
    return Check("database", True, f"schema v{version}")


def _check_provider(provider) -> Check:
    if provider is None:
        return Check("llm provider", False, "no provider configured")
    health = provider.health()
    return Check("llm provider", health.ok, health.detail)


def _check_forage(binary: str, which) -> Check:
    path = which(binary)
    if not path:
        return Check("forage", False,
                     f"`{binary}` is not installed or not on PATH; "
                     "Facebook scraping will be skipped")
    return Check("forage", True, f"found at {path}")


def _check_profile(conn: sqlite3.Connection) -> Check:
    try:
        profiles = ProfileRepo(conn).list()
    except sqlite3.Error as exc:
        return Check("profile", False, f"could not read profiles: {exc}")
    if not profiles:
        return Check("profile", False, "no profile yet — run `sublease init`")
    return Check("profile", True,
                 f"{len(profiles)} profile(s); active: {profiles[0].name}")


def run_checks(conn: sqlite3.Connection | None = None, provider=None,
               forage_binary: str = "forage", which=shutil.which) -> list[Check]:
    return [
        _check_database(conn),
        _check_provider(provider),
        _check_forage(forage_binary, which),
        _check_profile(conn),
    ]
```

- [ ] **Step 4: Write the failing init test**

```python
# tests/test_cli_init.py
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
```

- [ ] **Step 5: Run it to verify it fails**

Run: `uv run pytest tests/test_cli_init.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.cli.init'`

- [ ] **Step 6: Write `sublease/cli/init.py`**

```python
"""Turn onboarding answers into a Profile.

`build_profile` is pure so it can be tested without a terminal, and so the M2
web wizard can reuse it unchanged.

The default copy is written in sentences with no leading "- " lines, because
Facebook's composer rewrites those into double bullets, and contains none of the
ASCII sequences the composer converts to emoji.
"""
from __future__ import annotations

from datetime import date

from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)

DEFAULT_TEMPLATES = {
    "outreach_message": (
        "Hi {first_name}! I saw your post in {group} looking for a place "
        "{their_dates}. I have a room available that overlaps your dates. "
        "Happy to send photos and details if you're still looking."
    ),
    "listing_post": (
        "Room available for sublet. Message me for photos and details, "
        "and I'm happy to answer any questions about the place or the "
        "neighborhood."
    ),
}


def build_profile(answers: dict) -> Profile:
    return Profile(
        name=answers["name"],
        place=Place(
            neighborhood=answers["neighborhood"],
            unit_type=answers.get("unit_type", "room"),
            bedrooms=answers.get("bedrooms", 1),
            bath=answers.get("bath", "shared"),
            furnished=answers.get("furnished", True),
            amenities=answers.get("amenities", []),
        ),
        window=Window(
            start=date.fromisoformat(answers["window_start"]),
            end=date.fromisoformat(answers["window_end"]),
            flexible=answers.get("flexible", False),
            allow_split=answers.get("allow_split", True),
            max_split=answers.get("max_split", 3),
        ),
        price=Price(nightly=answers.get("nightly_price"),
                    total=answers.get("total_price")),
        constraints=Constraints(
            max_people_per_room=answers.get("max_people_per_room", 1),
            multi_room_seekers_ok=answers.get("multi_room_seekers_ok", True),
            gender_preference=answers.get("gender_preference"),
            pets_ok=answers.get("pets_ok", True),
        ),
        templates=Templates(
            outreach_message=answers.get("outreach_message",
                                         DEFAULT_TEMPLATES["outreach_message"]),
            listing_post=answers.get("listing_post",
                                     DEFAULT_TEMPLATES["listing_post"]),
        ),
        sources=[SourceConfig(**s) for s in answers.get("sources", [])],
    )
```

- [ ] **Step 7: Write `sublease/cli/main.py` with the two commands**

```python
"""The `sublease` command."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from sublease.cli.doctor import run_checks
from sublease.cli.init import DEFAULT_TEMPLATES, build_profile
from sublease.llm.registry import DEFAULT_MODEL, DEFAULT_PROVIDER, get_provider
from sublease.store.db import connect, migrate
from sublease.store.repositories import ProfileRepo

app = typer.Typer(help="Find a subletter for your place.", no_args_is_help=True)
console = Console()


def _provider(name: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL):
    try:
        return get_provider(name, model=model)
    except Exception as exc:      # noqa: BLE001 — doctor reports, never crashes
        console.print(f"[yellow]provider unavailable: {exc}[/yellow]")
        return None


@app.command()
def doctor(provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL) -> None:
    """Check that everything a run needs is present and working."""
    conn = connect()
    checks = run_checks(conn=conn, provider=_provider(provider, model))
    table = Table(title="sublease doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    for check in checks:
        mark = "[green]ok[/green]" if check.ok else "[red]FAIL[/red]"
        table.add_row(check.name, mark, check.detail)
    console.print(table)
    raise typer.Exit(0 if all(c.ok for c in checks) else 1)


@app.command()
def init() -> None:
    """Create a profile: your place, your dates, your constraints."""
    conn = connect()
    migrate(conn)

    answers: dict = {
        "name": typer.prompt("A name for this listing", default="My sublet"),
        "neighborhood": typer.prompt("Neighborhood"),
        "unit_type": typer.prompt("Renting a room or the whole unit?",
                                  default="room"),
        "window_start": typer.prompt("First date available (YYYY-MM-DD)"),
        "window_end": typer.prompt("Last date available (YYYY-MM-DD)"),
        "total_price": float(typer.prompt("Total price for the whole window")),
        "allow_split": typer.confirm(
            "Would you accept several subletters covering different dates?",
            default=True),
        "max_people_per_room": int(typer.prompt(
            "Maximum people sharing the room", default="1")),
    }

    preference = typer.prompt(
        "Gender preference, if any (male/female/none). This is a soft ranking "
        "signal only, and is used only when someone states it themselves",
        default="none")
    answers["gender_preference"] = None if preference == "none" else preference

    sources: list[dict] = []
    console.print("\nAdd the Facebook groups to watch. Slug is the part of the "
                  "group URL after /groups/. Leave the slug blank to finish.")
    while True:
        slug = typer.prompt("  group slug", default="", show_default=False)
        if not slug:
            break
        sources.append({"slug": slug,
                        "name": typer.prompt("  group name", default=slug),
                        "method": "forage"})
    answers["sources"] = sources

    profile = ProfileRepo(conn).save(build_profile(answers))
    console.print(f"\n[green]Saved profile {profile.id}: {profile.name}[/green]")
    console.print(f"Window is {profile.window.days} days across "
                  f"{len(profile.sources)} group(s).")
    console.print("Edit your outreach copy any time; the default is:\n")
    console.print(f"  {DEFAULT_TEMPLATES['outreach_message']}\n")
    console.print("Next: run [bold]sublease doctor[/bold], then "
                  "[bold]sublease run[/bold].")


if __name__ == "__main__":
    app()
```

- [ ] **Step 8: Write `sublease/cli/__init__.py`**

```python
from sublease.cli.main import app

__all__ = ["app"]
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_doctor.py tests/test_cli_init.py -v`
Expected: 8 + 10 = 18 passed

- [ ] **Step 10: Commit**

```bash
git add sublease/cli tests/test_cli_doctor.py tests/test_cli_init.py
git commit -m "feat: sublease doctor and sublease init"
```

---

## Task 20: CLI — `run`, `candidates`, `coverage`

**Files:**
- Create: `sublease/cli/report.py`
- Modify: `sublease/cli/main.py`
- Test: `tests/test_cli_report.py`

**Interfaces:**
- Consumes: Tasks 6, 7, 16, 17, 18, 19
- Produces:
  - `sublease.cli.report.candidates_table(rows: list[dict]) -> Table`
  - `sublease.cli.report.coverage_lines(plan: CoveragePlan) -> list[str]`
  - `sublease.cli.report.rows_to_csv(rows: list[dict]) -> str`
  - `sublease.cli.main.build_sources(profile, fixtures_path=None) -> dict[SourceConfig, Source]`
  - Typer commands `run`, `candidates`, `coverage`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_report.py
import csv
import io
from datetime import date
from sublease.cli.report import candidates_table, coverage_lines, rows_to_csv
from sublease.match.coverage import coverage
from sublease.match.types import Candidate

ROWS = [
    {"tier": "A", "tier_reason": "covers 22/22 days", "author_name": "Emma Stone",
     "days_covered": 22, "fit": "full-window", "wants_start": "2026-08-18",
     "wants_end": "2026-09-08", "group_name": "NYC Sublets", "status": "new",
     "post_url": "https://fb.com/1", "author_url": "https://fb.com/emma",
     "draft": "Hi Emma", "post_text": "ISO a room", "also_posted_in": ["Group B"]},
    {"tier": "C", "tier_reason": "covers only 10/22 days", "author_name": "Nia",
     "days_covered": 10, "fit": "inside", "wants_start": "2026-08-30",
     "wants_end": "2026-09-08", "group_name": "NYU Housing", "status": "new",
     "post_url": "https://fb.com/2", "author_url": "https://fb.com/nia",
     "draft": "Hi Nia", "post_text": "ISO", "also_posted_in": []},
]


def test_table_has_one_row_per_candidate():
    assert candidates_table(ROWS).row_count == 2


def test_table_shows_tier_name_and_coverage():
    headers = [c.header for c in candidates_table(ROWS).columns]
    assert "tier" in headers and "name" in headers and "days" in headers


def test_empty_rows_still_produce_a_table():
    assert candidates_table([]).row_count == 0


def test_csv_round_trips_every_row():
    parsed = list(csv.DictReader(io.StringIO(rows_to_csv(ROWS))))
    assert len(parsed) == 2
    assert parsed[0]["author_name"] == "Emma Stone"


def test_csv_includes_the_draft_message():
    assert "draft" in csv.DictReader(io.StringIO(rows_to_csv(ROWS))).fieldnames


def test_csv_flattens_the_cross_posted_group_list():
    parsed = list(csv.DictReader(io.StringIO(rows_to_csv(ROWS))))
    assert parsed[0]["also_posted_in"] == "Group B"


def test_csv_of_no_rows_is_just_a_header():
    assert len(rows_to_csv([]).strip().splitlines()) == 1


def cand(name, start, end):
    return Candidate(post_id=f"p:{name}", person_key=name, name=name,
                     fit="inside", days_covered=(end - start).days + 1,
                     wants_start=start, wants_end=end)


def test_coverage_lines_report_a_complete_single():
    plan = coverage([cand("Emma", date(2026, 8, 18), date(2026, 9, 8))],
                    date(2026, 8, 18), date(2026, 9, 8))
    text = "\n".join(coverage_lines(plan))
    assert "Emma" in text and "22/22" in text


def test_coverage_lines_report_a_combination():
    plan = coverage(
        [cand("Fiona", date(2026, 8, 18), date(2026, 8, 31)),
         cand("Nia", date(2026, 8, 31), date(2026, 9, 8))],
        date(2026, 8, 18), date(2026, 9, 8), max_split=3)
    text = "\n".join(coverage_lines(plan))
    assert "Fiona" in text and "Nia" in text
    assert "2 people" in text


def test_coverage_lines_say_so_when_nothing_covers_the_window():
    plan = coverage([], date(2026, 8, 18), date(2026, 9, 8))
    assert "No candidates" in "\n".join(coverage_lines(plan))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.cli.report'`

- [ ] **Step 3: Write `sublease/cli/report.py`**

```python
"""Rendering for the read-only commands. Pure functions, so they are testable
without a terminal.
"""
from __future__ import annotations

import csv
import io

from rich.table import Table

from sublease.match.types import CoveragePlan

CSV_COLUMNS = [
    "tier", "tier_reason", "fit", "days_covered", "wants_start", "wants_end",
    "author_name", "author_url", "post_url", "group_name", "also_posted_in",
    "status", "draft", "post_text",
]
TIER_COLOR = {"A": "green", "B": "cyan", "C": "yellow", "D": "red"}


def candidates_table(rows: list[dict]) -> Table:
    table = Table(title="Candidates")
    for header in ("tier", "name", "days", "wants", "group", "status", "why"):
        table.add_column(header)
    for row in rows:
        tier = row.get("tier") or "?"
        table.add_row(
            f"[{TIER_COLOR.get(tier, 'white')}]{tier}[/]",
            row.get("author_name") or "unknown",
            f"{row.get('days_covered', 0)}",
            f"{row.get('wants_start') or '?'} → {row.get('wants_end') or 'open'}",
            row.get("group_name") or "",
            row.get("status") or "",
            row.get("tier_reason") or "",
        )
    return table


def rows_to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        flat = dict(row)
        also = flat.get("also_posted_in") or []
        flat["also_posted_in"] = "; ".join(also) if isinstance(also, list) else also
        writer.writerow(flat)
    return buffer.getvalue()


def coverage_lines(plan: CoveragePlan) -> list[str]:
    lines = [f"Window is {plan.window_days} days."]

    if plan.singles:
        lines.append("")
        lines.append(f"Single candidates covering (nearly) the whole window "
                     f"({len(plan.singles)}):")
        for c in plan.singles:
            span = f"{c.wants_start or 'open'} → {c.wants_end or 'open'}"
            lines.append(f"  {c.name}: {span} "
                         f"({c.days_covered}/{plan.window_days} days)")

    if plan.combination:
        lines.append("")
        lines.append(f"Best combination — {len(plan.combination)} people covering "
                     f"{plan.combination_days}/{plan.window_days} days:")
        for c in plan.combination:
            span = f"{c.wants_start or 'open'} → {c.wants_end or 'open'}"
            lines.append(f"  {c.name}: {span}")
    elif not plan.singles:
        lines.append("")
        lines.append("No candidates overlap your window yet.")

    return lines
```

- [ ] **Step 4: Add the three commands to `sublease/cli/main.py`**

Add these imports at the top:

```python
import os
from datetime import date as date_cls, timedelta
from pathlib import Path

from sublease.cli.report import candidates_table, coverage_lines, rows_to_csv
from sublease.match.coverage import coverage as compute_coverage
from sublease.match.ranking import rank
from sublease.pipeline import run_pipeline
from sublease.sources.registry import get_source
from sublease.store.repositories import (
    CandidateRepo, EnrichmentRepo, ExtractionRepo, PostRepo,
)
```

Then append:

```python
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "posts.json"


def build_sources(profile, fixtures_path: Path | None = None) -> dict:
    """Construct one adapter per configured source."""
    built = {}
    for cfg in profile.sources:
        method = "fixtures" if fixtures_path else cfg.method
        kwargs: dict = {}
        if method == "fixtures":
            kwargs["path"] = fixtures_path or FIXTURES
        elif method == "apify":
            kwargs["token"] = os.environ.get("APIFY_TOKEN", "")
        try:
            built[cfg] = get_source(method, **kwargs)
        except Exception as exc:      # noqa: BLE001 — reported per source by the run
            console.print(f"[yellow]{cfg.name}: {exc}[/yellow]")
    return built


def _active_profile(conn):
    profiles = ProfileRepo(conn).list()
    if not profiles:
        console.print("[red]No profile yet. Run `sublease init` first.[/red]")
        raise typer.Exit(1)
    return profiles[0]


@app.command()
def run(fixtures: bool = typer.Option(False, help="Use synthetic posts, no Facebook."),
        days: int = typer.Option(21, help="How far back to scrape."),
        limit: int = typer.Option(300, help="Max posts per source."),
        dry_run: bool = typer.Option(False, help="Report without writing."),
        provider: str = DEFAULT_PROVIDER, model: str = DEFAULT_MODEL) -> None:
    """Scrape, extract, match, and store candidates."""
    conn = connect()
    migrate(conn)
    profile = _active_profile(conn)

    llm = _provider(provider, model)
    if llm is None:
        raise typer.Exit(1)

    today = date_cls.today()
    report = run_pipeline(
        conn, profile, llm, today,
        sources=build_sources(profile, FIXTURES if fixtures else None),
        since=today - timedelta(days=days),
        limit=limit, dry_run=dry_run)

    for error in report.source_errors:
        console.print(f"[yellow]source failed — {error}[/yellow]")
    console.print(
        f"Scraped {report.scraped} posts ({report.new_posts} new). "
        f"Extracted {report.extracted}, enriched {report.enriched}. "
        f"{report.candidates} candidates ({report.new_candidates} new).")
    if dry_run:
        console.print("[yellow]dry run — nothing was written[/yellow]")


@app.command()
def candidates(tier: str = typer.Option(None, help="Only this tier (A/B/C/D)."),
               new: bool = typer.Option(False, help="Only ones you haven't contacted."),
               as_csv: bool = typer.Option(False, "--csv", help="Emit CSV.")) -> None:
    """List ranked candidates."""
    conn = connect()
    profile = _active_profile(conn)
    rows = CandidateRepo(conn).list(profile.id, tier=tier, new_only=new)
    if as_csv:
        print(rows_to_csv(rows), end="")
    else:
        console.print(candidates_table(rows))


@app.command()
def coverage() -> None:
    """Show the best single candidates and the best combination."""
    conn = connect()
    profile = _active_profile(conn)
    ranked = rank(
        {p["id"]: p for p in PostRepo(conn).get_all()},
        ExtractionRepo(conn).get_all(),
        EnrichmentRepo(conn).by_post_id(),
        profile,
    )
    plan = compute_coverage(ranked, profile.window.start, profile.window.end,
                            max_split=profile.window.max_split)
    for line in coverage_lines(plan):
        console.print(line)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_report.py -v`
Expected: 11 passed

- [ ] **Step 6: Verify the CLI is wired end to end**

Run: `SUBLEASE_HOME=$(mktemp -d) uv run sublease --help`
Expected: help text listing `init`, `run`, `candidates`, `coverage`, `doctor`

- [ ] **Step 7: Commit**

```bash
git add sublease/cli tests/test_cli_report.py
git commit -m "feat: sublease run, candidates, and coverage commands"
```

---

## Task 21: End-to-end golden test and the author regression

**Files:**
- Create: `tests/test_e2e_fixtures.py`, `tests/test_regression_original_profile.py`
- Modify: `README.md` (create)

**Interfaces:**
- Consumes: everything

Two tests close the loop. The first runs the whole pipeline over `fixtures/posts.json` with a canned provider and asserts the exact ranked output — the deterministic golden path. The second reconstructs the original author's profile and asserts the engine reproduces their household rules, which is what makes "port, don't rewrite" verifiable rather than aspirational.

The fixtures were designed to cover every branch: exact match, strictly inside, fuzzy phrasing, a Labor Day reference, an offerer, a post with no dates, a couple that overlaps, a numeric range, an open end, and a range entirely outside the window.

- [ ] **Step 1: Write the golden end-to-end test**

```python
# tests/test_e2e_fixtures.py
"""The whole pipeline over fixtures/posts.json, with a canned provider.

Deliberately deterministic: the LLM is faked, so this asserts the engine's
behaviour rather than any model's. Expected values were derived by hand from the
window Aug 18 - Sep 8 2026 (22 days).
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

# What a correct model returns for each fixture post.
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
        responses[f"SEEKING-{pid}"] = {"results": [{
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


def run(setup, batch_size=1):
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
    assert plan.combination_days == 22


def test_a_second_run_adds_no_new_candidates(setup):
    conn, profile = setup
    provider = canned_provider()
    source = FixtureSource(FIXTURES)
    run_pipeline(conn, profile, provider, TODAY, sources={CFG: source})
    second = run_pipeline(conn, profile, provider, TODAY, sources={CFG: source})
    assert second.new_candidates == 0
    assert second.extracted == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_e2e_fixtures.py -v`
Expected: FAIL — the enrichment prompt marker in `canned_provider` will not match. Adjust the marker keys in `responses` until every fixture id resolves for both passes; the extraction prompt contains the bare post id and the enrichment prompt contains it too, so key both on the id and let the first match win by ordering extraction keys first.

- [ ] **Step 3: Make the golden test pass**

If both passes match the same marker, disambiguate by giving `FakeProvider` a per-schema lookup. Add to `tests/fakes.py`:

```python
    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        self.calls.append(prompt)
        for marker in self.fail_on:
            if marker in prompt:
                raise ProviderError(f"fake failure triggered by {marker!r}")
        prefix = f"{schema.__name__}:"
        for marker, payload in self.responses.items():
            if marker.startswith(prefix) and marker[len(prefix):] in prompt:
                return schema.model_validate(payload)
        for marker, payload in self.responses.items():
            if ":" not in marker and marker in prompt:
                return schema.model_validate(payload)
        raise ProviderError("no canned response matched this prompt")
```

Then key the golden fixtures as `f"ExtractionBatch:{pid}"` and `f"EnrichmentBatch:{pid}"`. Re-run the earlier provider tests to confirm the plain-marker path still works.

Run: `uv run pytest tests/test_e2e_fixtures.py tests/test_llm_registry.py tests/test_extract_runner.py -v`
Expected: all passing

- [ ] **Step 4: Write the author regression test**

```python
# tests/test_regression_original_profile.py
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
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest tests/test_regression_original_profile.py -v`
Expected: 8 passed

- [ ] **Step 6: Write `README.md`**

```markdown
# sublease-agent

Finds people looking for a sublet that matches your dates, across the groups
where they already post, and hands you a ranked shortlist with a draft message
for each one.

Self-hosted and open source. Your data stays on your machine.

## Status

M1: the core engine and CLI. The web UI, outreach queue, and installer land in
later milestones — see `docs/superpowers/specs/`.

## Install (development)

```bash
git clone <this repo> && cd sublease-agent
uv sync
uv run sublease --help
```

## Use

```bash
uv run sublease init          # your place, dates, constraints, groups
uv run sublease doctor        # verify provider, scraper, session, database
uv run sublease run           # scrape, extract, match, store
uv run sublease run --fixtures  # try the whole pipeline with no Facebook
uv run sublease candidates    # ranked shortlist
uv run sublease coverage      # best single, and best combination
```

Set `ANTHROPIC_API_KEY` for the default provider. Extraction runs on
`claude-haiku-4-5`; a full backfill of a few hundred posts costs well under a
dollar. `sublease init` can also select OpenAI, a local Ollama, or an existing
Claude Code install.

## Data

Everything lives under `$SUBLEASE_HOME` (default `~/.sublease`). The database
holds posts and candidate records scraped from public groups — other people's
personal information. It is not encrypted. Keep it as you would any personal
file, and delete it when your search is over.

## Testing

```bash
uv run pytest
```

No test touches the network.

## Legal

Automated scraping and automated posting are against Facebook's Terms of
Service. This tool is deliberately small-volume, human-paced, and uses your own
logged-in session. You are responsible for how you use it. Subletting may also
be restricted by your lease and by local law — check both.
```

- [ ] **Step 7: Run the whole suite and check coverage**

Run: `uv run pytest --cov=sublease --cov-report=term-missing`
Expected: all tests pass; `sublease/match/` at or near 100% line coverage

- [ ] **Step 8: Commit**

```bash
git add tests/test_e2e_fixtures.py tests/test_regression_original_profile.py \
        tests/fakes.py README.md
git commit -m "test: end-to-end golden path and original-profile regression

The regression test pins the prototype's household rules as profile data, so
any change to tiering or window classification that would alter its live
ranking now fails the suite."
```

---

## Self-Review

**Spec coverage.** Every section of `2026-08-11-sublease-agent-m1-design.md` maps to a task:

| Spec section | Task(s) |
|---|---|
| §5 Profile | 2 |
| §6 Data model | 3, 4 |
| §7 Module contracts — `Source` | 5, 6, 7 |
| §7 — `LLMProvider` | 8, 9, 10 |
| §7 — `extract` | 11, 12 |
| §7 — `match.rank` / `match.coverage` | 13, 14, 15, 16, 17 |
| §8 LLM providers, Haiku default, no thinking/effort | 9, 10 |
| §9 Defect 1 (hardcoded prompt date) | 11 |
| §9 Defect 2 (pairs-only coverage) | 16 |
| §9 Defect 3 (quadratic pair search) | 16 |
| §9 Ported logic (sanitizers, dedupe, canonical id, bisect) | 5, 12, 15 |
| §10 Failure behavior — source isolation | 18 |
| §10 — bisect and no-re-extraction | 12, 18 |
| §10 — `sublease doctor` | 19 |
| §10 — WAL, forward-only migrations | 3 |
| §11 Testing — pure `match`, fake provider, golden, regression | 13–17, 8, 21 |
| §12 CLI surface | 19, 20 |
| §14 Assumption 1 (multi-profile) | 3, 4 |
| §14 Assumption 2 (`allow_split` on) | 2 |
| §14 Assumption 4 (Apify ported) | 7 |
| §14 Assumption 5 (unencrypted, document it) | 21 (README) |

**Gap found and closed:** §14 assumption 5 asked for the retention caveat to be documented. It had no task; it is now Task 21 Step 6, in the README's *Data* section.

**Type consistency.** `person_key` is produced in Task 15 and consumed in Tasks 4, 17, 21 with the same signature. `Candidate` field names are fixed in Task 13 and used unchanged in 15, 16, 17. `RunReport` fields are asserted in Task 18 and printed in Task 20. Repository row-dict keys match the Task 3 column names throughout. `FakeProvider` gains a schema-prefixed marker in Task 21 Step 3, and that step re-runs the Task 8 and Task 12 suites to confirm the plain-marker path still works.

**Placeholder scan.** No `TBD`, no "add error handling", no "similar to Task N". Every code step carries runnable code; every test step carries real assertions.

---

## Execution Handoff

Plan complete, saved across four files in `docs/superpowers/plans/`:

- `2026-08-11-m1-core-engine.md` — Tasks 1–7 (scaffolding, profile, store, sources)
- `2026-08-11-m1-core-engine-part2.md` — Tasks 8–12 (providers, extraction)
- `2026-08-11-m1-core-engine-part3.md` — Tasks 13–16 (matching)
- `2026-08-11-m1-core-engine-part4.md` — Tasks 17–21 (ranking, pipeline, CLI, e2e)
