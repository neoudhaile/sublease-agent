# sublease-finder — design spec (approved 2026-08-11)

## Goal
Fill an East Village apartment sublease for **Aug 18 – Sep 8, 2026** (22 days)
as fast as possible by finding people *seeking* sublets in NYC Facebook groups
and producing a ranked, contact-ready candidate list.

## Approved decisions
- **Hybrid scraping**: ForageFacebook (Playwright CLI, user's own FB session)
  for private groups; Apify `facebook-groups-scraper` for public groups
  (skipped unless `APIFY_TOKEN` is set).
- **Filter on dates only** — any seeker whose requested timeframe falls inside
  the window qualifies. No filtering on budget, gender, neighborhood, etc.
  Near-misses that spill outside the window are kept, flagged `overlap`.
- **Outreach**: CSV includes a personalized draft message per candidate; the
  user sends messages themselves (no automated DMs — account-ban risk).
- **Automated runs every 2 hours (8am–8pm) through Aug 18** (updated from daily
  8am on 2026-08-11), light `--days 3` scrapes, appending new candidates only.
  Extraction runs on Haiku only.
- **Standby scraper**: `vendor/fb-group-monitor` (user-supplied, security
  reviewed) is vendored dormant; its SQLite output is auto-ingested when
  present, with canonical `fbpost:<id>` IDs deduping across scrapers.

## Pipeline
```
groups.yaml → pipeline/scrape.py → cache/posts.jsonl (normalized, deduped)
            → pipeline/extract.py → cache/extracted.jsonl
              (claude -p haiku: is_seeking, start/end date, budget, confidence;
               handles fuzzy language like "last two weeks of August",
               "through Labor Day"; results cached per post id)
            → pipeline/filter_rank.py → out/candidates.csv, out/new_candidates.csv,
              out/coverage_report.md
```

## Ranking
Sort by days-of-window covered (desc), then fit
(`full-window` > `inside` > `wants-more` > `overlap`), then post recency.
Open-ended requests ("from Aug 22, flexible") are treated optimistically as
running to the window end. The coverage report lists near-complete single
candidates and the best complementary pairs (e.g. Aug 18–31 + Sep 1–8) so the
whole duration can be filled by two people if needed.

## Known risks
- Scraping violates Facebook ToS; mitigated by real session, slow delays,
  small volume. Apify path carries no account risk (public groups only).
- Forage sessions expire (~30 days) — `forage login` may need re-running.
- Facebook DOM changes can break Forage; fallback is Claude-driven Chrome.
- Sublets under 30 days are a legal gray zone in NYC — user acknowledged.
