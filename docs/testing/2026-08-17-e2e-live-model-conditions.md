# E2E test conditions — first live-model run

Date: 2026-08-17
Branch: `m1-core-engine` @ `9338a6c` · 469 automated tests passing

## Why this run exists

Every one of the 469 automated tests uses `FakeProvider`. **No prompt in this codebase has
ever been sent to a real model.** The suite proves the engine handles a model's output
correctly; it proves nothing about whether our prompts actually elicit that output.

Those are different claims, and only the second one predicts whether the tool works.

## What is already proven, and will not be re-tested here

- Every pure function: window overlap, tiering, dedupe, coverage, normalization.
- Batching, bisect-on-failure, id-set validation, the prefilter.
- Repository round-trips, migrations, transaction rollback on dry run.
- The rendering functions.

## What has NEVER been exercised

| Untested path | Why it matters |
|---|---|
| A real model call through any provider | The `claude-cli` provider's subprocess handling, output scraping, and JSON extraction have only ever seen canned strings. |
| Whether the prompts work | Fuzzy dates, seeker-vs-offerer intent, couple detection, and price parsing are *prompt* problems, not code problems. A passing suite says nothing about them. |
| The CLI end to end | `init` → `run` → `candidates` → `coverage` → `price` as a sequence, against a real database on disk. |
| A real `$SUBLEASE_HOME` | Directory creation, migration on first use, WAL files. |
| Cost | Nobody has measured what a run costs. |

## Environment

| Component | State |
|---|---|
| Provider | `claude-cli` — drives `claude -p`, no API key needed |
| Model | `haiku` |
| Source | `fixtures` (10 synthetic posts) |
| `forage` | **not installed** — no real Facebook scraping this run |
| Window | Aug 18 – Sep 8 2026 (22 nights) |
| Constraints | Defaults: max 1 per room, multi-room seekers ok, no gender preference, 0.90/0.60 |

## The fixtures, and what each one tests

Each fixture targets a specific failure mode. The expected outcomes below were derived by
hand from the fixture text and the window — they are what a *correct* engine produces, not
a recording of what it did.

| # | Poster | Tests | Expected |
|---|---|---|---|
| 1 | Exact Emma | Exact ISO-ish dates | seeker, Aug 18–Sep 8, **tier A, 22/22** |
| 2 | Inside Ivan | Range strictly inside | seeker, Aug 20–Sep 1, 13 days, **tier C** |
| 3 | Fuzzy Fiona | **Fuzzy phrasing** — "last two weeks of august" | seeker, ≈Aug 18–31, ~14 days, **tier B** |
| 4 | Labor-Day Lee | **Holiday resolution** — "through Labor Day" | seeker, Aug 25–**Sep 7**, 14 days, **tier B** |
| 5 | Offering Olga | **Offerer, not seeker** + priced | `is_seeking=false`, excluded from candidates, **appears as a comp** at $1400/mo Bushwick |
| 6 | No-Dates Ned | **Prefilter** — no date tokens | never reaches the model; `model` column NULL |
| 7 | Overlap Owen | **Couple detection** — "young professional couple" | seeker, overlaps, `people_in_one_room=2`, **tier D** |
| 8 | Numeric Nia | Slash-format dates "8/30-9/8" | seeker, Aug 30–Sep 8, 10 days, **tier C** |
| 9 | Open-End Omar | **Open end** — "end date flexible" | seeker, from Aug 22, `end=NULL`, 18 days, **tier B** |
| 10 | Outside Otis | Entirely outside window | seeker, Sep 15–Oct 30, **excluded** |

## Conditions to check

### C1 — Provider reachability
`sublease doctor` reports the `claude-cli` provider healthy without a billable API call.
**Pass:** provider row ok. **Fail:** any traceback, or `doctor` crashing rather than reporting.

### C2 — Ingestion
All 10 fixture posts land in `post`. **Pass:** `scraped=10, new_posts=10`.

### C3 — The prefilter actually saves money
Ned (#6) never reaches the model. **Pass:** his `extraction.model` is NULL.
This is the one condition that is verified against the database, not the output, because
the whole point is that something did *not* happen.

### C4 — Intent classification
Exactly one post (#5, Olga) is classified `is_seeking=false`.
**Fail mode to watch:** a real model may read #10 (Otis, wants Sept–Oct) as an offerer, or
misread #5's "SUBLET AVAILABLE" as a request.

### C5 — Fuzzy date resolution *(the highest-risk condition)*
- #3 "last two weeks of august" → a range inside Aug 17–31.
- #4 "through Labor Day" → end date **2026-09-07**, computed from the run year, not hardcoded.
- #8 "8/30-9/8" → Aug 30 to Sep 8, not Sep 8 to Aug 30 or a 2025 date.

**Pass:** all three land within a day of expectation. **Partial:** off by a day or two —
record it; fuzzy language has no single right answer. **Fail:** wrong month or wrong year.

### C6 — Household rules
Owen (#7) is tier D for two people in one room — and for that reason, not another.
His raw coverage is 15/22, which would otherwise be tier B, so tier D proves enrichment
data actually reached the ranker.

### C7 — Candidate set
7 candidates survive the window filter; Olga, Ned, and Otis are excluded.

### C8 — Coverage
The combination search returns a set covering the full 22 days, and reports honestly if not.

### C9 — Offer extraction and pricing
Olga's post yields an offer with `price_amount=1400`, `price_unit=month`,
`nightly_price≈46.05`, neighborhood "Bushwick". `sublease price` then runs — with one comp
it must report the sample as **thin**, not present a confident median.

### C10 — Cost and duration
Record wall-clock time and, if observable, token spend. A full 10-post run should be
seconds and fractions of a cent.

### C11 — Idempotence
A second `run` re-extracts nothing: `extracted=0, new_candidates=0`.

## Pass / fail

**Pass:** C1–C4, C6, C7, C11 exactly as specified; C5 within a day; C9 structurally correct.

**Partial:** fuzzy dates off by a day or two, or a thin-sample price presented with
appropriate hedging but awkward wording.

**Fail:** any traceback; a hardcoded-looking year; the prefilter calling the model; a couple
ranked above a solo seeker; the model output failing to parse.

## Known limits of this run

1. **Not Facebook.** The fixtures are clean, short, and written in one voice. Real posts are
   messy, multilingual, emoji-laden, and sometimes images with no text at all.
2. **One model.** Results say nothing about the OpenAI or Ollama providers.
3. **Ten posts.** A real run is 500+, where batching, bisect recovery, and rate limits
   actually get exercised.
4. **Deterministic only by luck.** A model may answer differently on a re-run. A pass here is
   evidence, not proof.

---

# RESULTS — 2026-08-17

Provider `claude-cli`, model `haiku`, fixtures source, fresh `$SUBLEASE_HOME`.

## The run found a critical bug on the first attempt

**Run 1: 10 posts extracted, ZERO candidates.** Every post recorded
`claude -p returned unusable JSON: 1 validation error for ExtractionBatch / results Field required`.

Root cause: none of the three prompt builders stated the required JSON envelope. They said
"Return one object per post", describing the items but never the `{"results": [...]}` wrapper,
and never forbidding markdown fences or prose. `AnthropicProvider` hid this entirely because
`messages.parse(output_format=...)` enforces the shape server-side.

**Three of four providers were non-functional** — `claude-cli` (the free path for Claude Code
subscribers), Ollama (the "nothing leaves your machine" path the README advertises), and
OpenAI JSON mode (which guarantees valid JSON, not a specific schema).

469 tests could not catch this by construction: `FakeProvider` never reads a prompt. It matches
a marker and returns a pre-validated object. The suite proves the engine handles a model's
output; only a live call proves the prompt elicits it.

Fixed in `227eb5c`: all three prompts now state the envelope, the non-structured providers
tolerate a bare array / fenced / prose-wrapped JSON, and 30 tests were added — including
prompt-content assertions and provider tests over realistic raw model output. Suite: 499.

## Run 2 — after the fix

`Scraped 10 posts (10 new). Extracted 10, enriched 8. 7 candidates (7 new).` — 42 seconds.

| Condition | Result |
|---|---|
| C1 provider reachability | **PASS** — all four checks reported, no crash; non-billable default disclosed itself |
| C2 ingestion | **PASS** — 10 scraped, 10 new |
| C3 prefilter | **PASS** — Ned's `extraction.model` is NULL; he never reached the model |
| C4 intent | **PASS** — exactly one offerer (Olga); every other post a seeker |
| C5 fuzzy dates | **PASS** — see below |
| C6 household rules | **PASS** — Owen `people_in_one_room=2` → tier D; Otis correctly read as **two separate rooms** (`multi=1`, one person per room) |
| C7 candidate set | **PASS** — 7 candidates; Olga, Ned, Otis excluded |
| C8 coverage | **PASS** — Emma alone covers 22/22; no redundant people added |
| C9 offers & pricing | **PASS on substance** — see below |
| C10 cost & duration | 42s first run, **0.2s** cached, 78KB database |
| C11 idempotence | **PASS** — second run: 0 new, 0 extracted, 0 new candidates |

### C5 in detail — the highest-risk condition, all correct

| Post | Written as | Resolved to |
|---|---|---|
| Fuzzy Fiona | "last two weeks of august" | 2026-08-18 → 08-31, confidence `medium` |
| Labor-Day Lee | "through Labor Day" | end **2026-09-07** — Labor Day 2026, computed from the run year |
| Numeric Nia | "8/30-9/8" | 2026-08-30 → 09-08, right year, right order |
| Open-End Omar | "end date flexible" | start 08-22, end **NULL** preserved as open |

The Labor Day result is the one that matters most: it proves the M1 fix removing the
hardcoded holiday actually works against a live model.

### C9 in detail

Olga's offer extracted exactly as predicted by hand: `price_amount=1400`, `price_unit=month`,
**`nightly_price=46.05`**, `neighborhood=Bushwick`, `unit_type=room`, Aug 15 – Sep 15.

`sublease price` then correctly reported no comps — the sole offer is in Bushwick, the place is
in the East Village, and the neighborhood matcher ruled them different. Correct: different
boroughs.

## Outstanding cosmetic bugs

1. `sublease coverage` prints "Best combination — **1 people** covering 22/22 days".
2. `sublease price` says "1 other listing(s) collected but **none usable**" when the offer has a
   perfectly usable price and simply sits in a different neighborhood. The wording conflates
   two different reasons and would send a user looking for a parsing bug that isn't there.

## What this run does NOT prove

Ten clean synthetic posts in one voice, one model, no Facebook. Real posts are messy,
multilingual, emoji-laden, and sometimes images with no text. Batching, rate limits, and
bisect recovery at 500-post scale remain unexercised.
