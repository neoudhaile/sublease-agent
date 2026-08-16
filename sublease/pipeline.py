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

    # Stages 2-5 write to the database, so a dry run executes the exact same
    # code as a real run inside a transaction and then rolls it back, rather
    # than re-implementing the computation separately. That keeps the preview
    # honest by construction: there is only one code path to drift from.
    conn.execute("BEGIN")
    try:
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
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("ROLLBACK" if dry_run else "COMMIT")
    return report
