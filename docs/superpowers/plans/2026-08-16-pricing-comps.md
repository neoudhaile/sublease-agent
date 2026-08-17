# Pricing comps — implementation plan

> **For agentic workers:** implement task-by-task. Each task ends with tests passing and a commit.

**Goal:** tell a user what comparable rooms cost per night in their neighborhood, so they can price theirs — optionally, during `init`, and any time after via `sublease price`.

**Architecture:** a third extraction pass over the non-seeker posts the engine already scrapes and currently discards, normalized to a per-night figure, matched to the user's place by the model rather than an alias table. Falls back to a model estimate when no local comps exist yet, which is the case during `init` on a first run.

**Spec:** `docs/superpowers/specs/2026-08-16-pricing-comps-design.md` — read it before Task 1.

## A note on this plan's format

The M1 plan carried verbatim test code. Six separate defects came from it: an expectation
derived from `date.today()`, three miscounts, a fixture marker that matched every prompt,
and a `None` that defeated a dataclass default. Specific-looking test code encoded my
mistakes as authoritative and implementers transcribed them faithfully.

So this plan states **behavior precisely and leaves the tests to the implementer.** Every
task lists what must be true; write the tests that prove it. Reviewers will judge whether
the tests actually pin the behavior rather than merely exercising the code.

## Global Constraints

- Python 3.12+; matches the existing codebase's conventions — read neighbouring modules first.
- **No test touches the network.** Use `FakeProvider` from `tests/fakes.py` for every model call.
- Conventional commit prefixes.
- Pure functions stay pure: no clock reads, no I/O. Dates and "today" are parameters.
- Every failure surfaces as a typed error from `sublease/errors.py`, never a raw exception.
- Extraction is write-once and cached by post id, exactly like `extraction` and `enrichment`.
- **A comp that cannot be converted to a per-night price is DROPPED, never estimated.** A wrong
  comp moves the median invisibly; a missing one is merely a smaller sample.

---

## Task 1: `offer` table and `OfferRepo`

**Files:** `sublease/store/schema.py` (append migration), `sublease/store/repositories.py`, `sublease/store/__init__.py`, tests.

**Do:**
- Append a **new migration** to `MIGRATIONS` creating the `offer` table exactly as specified in the design doc. Do not edit the existing `_V1` — migrations are forward-only and `migrate()` applies each inside its own transaction.
- Add `OfferRepo(conn)` with `.save_many(rows, now=None)`, `.by_post_id() -> dict[str, dict]`, `.done_ids() -> set[str]`, and `.usable(neighborhood_filter=None) -> list[dict]` returning only offers with a non-null `nightly_price`.
- Follow `ExtractionRepo` and `EnrichmentRepo` for shape, naming, and `ON CONFLICT DO NOTHING` semantics.
- Export from `sublease/store/__init__.py`.

**Must be true:**
- A fresh database migrates to the new version; an existing v1 database migrates forward without data loss. Test both — the second is the one that matters and the one nobody writes.
- `schema_version` reflects the new count.
- Rows round-trip; `save_many` is idempotent.
- `usable()` excludes offers with a null `nightly_price`.
- Every existing store test still passes untouched.

---

## Task 2: offer extraction

**Files:** `sublease/extract/schemas.py`, `sublease/extract/prompts.py`, `sublease/extract/runner.py`, tests.

**Do:**
- Add `OfferItem` / `OfferBatch` Pydantic schemas carrying: `id`, `price_amount`, `price_unit` (`night|week|month|period`), `currency`, `neighborhood`, `unit_type` (`room|whole_unit`), `bedrooms`, `bath`, `furnished`, `start_date`, `end_date`. Dates and numbers are permissive types parsed by the runner, matching how `ExtractionItem` handles dates today — providers vary and Ollama enforces nothing.
- Add `build_offer_prompt(posts, today)`. It extracts what a listing is offering and for how much. It must:
  - take the reference date as a parameter and compute any date facts from it (the M1 prototype hardcoded these and silently mis-resolved every relative phrase — do not reintroduce that);
  - instruct that a price stated for the whole stay is `period`, and that `period` is only useful alongside dates;
  - ask for the neighborhood **as written**, not normalized — normalization happens later, by the model, at comparison time.
- Add `run_offer_extraction(posts, provider, today, batch_size=12)` mirroring `run_extraction`: batching, bisect-on-failure, one row per post, and a prefilter that skips posts with no price-like token before they cost a model call.

**Must be true:**
- Only non-seeker posts are candidates for this pass — the caller selects them; the runner does not re-decide intent.
- Every post sent produces exactly one row, including skipped and failed ones. This is why `ids_without_offer`-style queries terminate; M1 hit a real bug here where a dropped post was re-selected and re-paid for forever.
- A failing batch bisects to isolate the offending post rather than losing the batch.
- The result id set is validated against the sent id set — a duplicated, missing, or unknown id is a batch failure. M1's runner needed this exact fix.
- Prefiltered posts record a null model, provably never reaching the provider.

---

## Task 3: normalization and comp selection

**Files:** `sublease/pricing/__init__.py`, `sublease/pricing/normalize.py`, `sublease/pricing/comps.py`, tests.

**Do:**
- `normalize_nightly(price_amount, price_unit, start, end) -> float | None` — the conversion table in the design doc. Month divides by 30.4, week by 7, night is identity, period divides by the offer's own inclusive night count. Returns `None` when not derivable; never guesses.
- `CompSet` value object: `comps: list[dict]`, `median: float | None`, `low`, `high`, `count`, `dropped`, `thin: bool`.
- `select_comps(offers, place, neighborhood_matches) -> CompSet` — filters by unit type (hard), ranks by bedroom similarity (soft), drops offers with no `nightly_price`, counts what it dropped, and flags `thin` below five comps.
- `neighborhood_matches` is injected as a callable so the module stays pure and testable without a model. The model-backed implementation lives in Task 4.

**Must be true:**
- Every price form in the design doc's table converts correctly, including inclusive night counting (Aug 18–Sep 8 is 22 nights, not 21 — the M1 engine is inclusive throughout and a mismatch here would be invisible).
- A period price without dates yields `None` and is counted as dropped, not zero.
- Zero or negative amounts, and a zero-night range, yield `None` rather than raising or producing infinity.
- A room never compares against a whole unit.
- `thin` is set below five comps and the median is still reported alongside it, not suppressed.
- Median of an even-sized sample is defined and tested.
- These modules import nothing from `sublease.store` or any provider.

---

## Task 4: `sublease price` and the optional `init` step

**Files:** `sublease/pricing/service.py`, `sublease/cli/price.py`, `sublease/cli/main.py`, `sublease/cli/init.py`, tests.

**Do:**
- `sublease/pricing/service.py`: given a connection, a place, a window and a provider, return either real comps or an estimate.
  - **Comps mode** when usable offers exist: build the `neighborhood_matches` callable from a model call that decides, given the user's neighborhood and a batch of comp neighborhood strings, which refer to the same or an adjacent area. Adjacent is labelled, not silently mixed.
  - **Estimate mode** when they do not: one model call returning a per-night estimate with a low/high range for the place spec and neighborhood. It must be surfaced as an estimate, and must never be presented as though comps existed.
- `sublease price` command: prints the median, range, count, the total for the user's window, and the individual comps. Reuses the existing `_active_profile` helper and the `_provider()` tuple convention in `main.py` — read that file, it returns `(provider, error)`.
- `init`: after the price question, offer the check **only if the user has not already given a price**, and let them decline. Declining must leave the flow exactly as it is today. Accepting shows the result and offers to use the suggested figure or enter their own.

**Must be true:**
- `init` still completes with the check declined, and with it accepted, and when the model is unavailable. It must never block onboarding.
- Estimate mode is visibly labelled as an estimate wherever it appears.
- Thin samples are reported as thin.
- A user who already entered a price is not asked.
- Rendering functions are pure — data in, string or table out — like `sublease/cli/report.py`.
- Nothing wraps a database transaction around `run_pipeline` or its callers; it opens its own `BEGIN` and a nested one raises.
- `uv run sublease --help` lists `price`, and the whole suite passes.
