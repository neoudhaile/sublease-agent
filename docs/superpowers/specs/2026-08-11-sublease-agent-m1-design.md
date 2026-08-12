# Sublease Agent — M1 Design (Core Engine + CLI)

Date: 2026-08-11
Status: approved for implementation planning

## 1. Context

A working single-user prototype lives at `~/sublease-finder` (~1,350 lines of Python,
copied into `reference/` here for porting). In one day of live operation it scraped 533
posts from ~10 NYC Facebook housing groups, extracted 125 matching candidates, and
produced same-day inbound conversations and a viable three-person split covering the
subletter's full window.

The prototype works. It is also welded to one person's sublease:

| Welded to the original author | Location in `reference/` |
|---|---|
| Window `2026-08-18 → 2026-09-08` | `groups.yaml` |
| Household rules (no couples; prefers male) | `pipeline/filter_rank.py:33-60` |
| Outreach and listing copy | `message_template.txt`, `listing_post.txt` |
| The ten NYC group slugs | `groups.yaml` |
| CRM target (a specific Notion page id) | `groups.yaml` |
| Posting state, as prose | `POSTING_SOP.md` |
| LLM access via a `claude -p` subprocess | `pipeline/extract.py:50` |

This document specifies **M1**: turning that prototype into a config-driven, tested
Python package that any user can point at their own sublease. It is the first of four
milestones toward an open-source, self-hosted tool with a local web UI.

## 2. Product decisions already made

These were settled before this design and are treated as fixed inputs:

- **Distribution**: open source, self-hosted. No servers, no hosted accounts, no
  custody of user or candidate data by the maintainer.
- **Install**: a one-line installer (`curl … | sh`) that provisions `uv`, Python,
  dependencies, and Playwright's browser, then `sublease start` opens a local UI.
- **Execution mode**, chosen during onboarding:
  - `manual` — the app drafts, the human sends.
  - `autopilot` — the agent posts, comments, and DMs unattended, opt-in behind an
    explicit risk disclosure.
- **Storage**: SQLite is the source of truth. Notion becomes an optional one-way
  mirror, so the tool works with no Notion account.
- **UI**: React SPA + FastAPI, with the built SPA shipped inside the Python wheel so
  end users never need Node.

## 3. M1 scope

**In scope.** A config-driven, tested Python package plus a CLI. Done when a stranger
can define their own profile and get a correctly ranked candidate list from their own
Facebook groups — everything the prototype does, minus the parts specific to its author.

**Out of scope for M1**, deferred to later milestones:

| Deferred | Milestone |
|---|---|
| Web API, React SPA, onboarding wizard, candidate board | M2 |
| Outreach queue, guardrails, both executors, autopilot | M3 |
| Notion mirror, one-line installer, scheduler, docs | M4 |
| Instagram handle extraction (`reference/pipeline/instagram.py`) | dropped — low value |

## 4. Architecture

```
sublease/
  profile/    place · window · price · constraints · templates · sources
  store/      SQLite schema, migrations, repositories
  sources/    Source protocol; ForageFacebook, Apify, fixtures
  llm/        provider protocol; anthropic, openai, ollama, claude-cli
  extract/    pass 1 (intent + dates), pass 2 (household fit)
  match/      overlap, tiering, person dedupe, coverage — pure functions
  outreach/   draft rendering + sanitizers (executors land in M3)
  sync/       Notion mirror (M4)
  scheduler/  jittered daytime runs (M4)
  web/        FastAPI app + built SPA (M2)
  cli/        init | run | candidates | coverage | doctor  (+ `start` in M2)
web/          React source, built into sublease/static/
```

The guiding rule for M1 is **port, don't rewrite**. The tiering rules, the fuzzy-date
prompt, person-level dedupe, coverage pairing, the canonical post id, and the Messenger
and Notion sanitizers all survived contact with production and move across close to
verbatim. What changes is that their hardcoded constants become fields on a profile.

## 5. The profile

`Profile` is a Pydantic model persisted per user. It replaces `groups.yaml`, the
constants in `filter_rank.py`, and the two copy templates.

```python
class Constraints(BaseModel):
    max_people_per_room: int = 1        # >= this many in one room -> tier D
    multi_room_seekers_ok: bool = True  # needing 2 rooms != a couple sharing 1
    gender_preference: Literal["male", "female", None] = None  # soft, self-stated only
    tier_a_coverage: float = 0.90
    tier_b_coverage: float = 0.60
    pets_ok: bool = True
    deposit_terms: str | None = None

class Window(BaseModel):
    start: date
    end: date
    flexible: bool = False
    allow_split: bool = True            # find combinations, not just single seekers
    max_split: int = 3                  # ceiling on seekers tiling the window

class Profile(BaseModel):
    id: int
    name: str
    place: Place                        # neighborhood, unit_type, bedrooms, bath,
                                        # furnished, amenities[], photos[]
    window: Window
    price: Price                        # nightly | total, each derives the other
    constraints: Constraints
    templates: Templates                # outreach_message, listing_post
    sources: list[SourceConfig]         # platform, slug, name, method, rules
```

The defaults reproduce the original author's setup exactly, which makes their live run
a regression fixture: same inputs through the new engine must yield the same ranking.

`gender_preference` is honored only when a seeker states their own gender in their post.
It is never inferred from a name or a photo. This is enforced in the enrichment prompt
and asserted in tests.

## 6. Data model

One SQLite file (`data/sublease.db`), WAL mode, forward-only versioned migrations
applied at startup. Posts and their LLM extractions are **global**; candidates and
outreach are **per profile**, so two profiles on one machine share the extraction cache
and never pay to parse the same post twice.

```sql
CREATE TABLE profile (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, place JSON NOT NULL,
  window_start DATE NOT NULL, window_end DATE NOT NULL,
  flexible BOOL NOT NULL DEFAULT 0, allow_split BOOL NOT NULL DEFAULT 1,
  max_split INT NOT NULL DEFAULT 3,
  price JSON NOT NULL, constraints JSON NOT NULL, templates JSON NOT NULL);

CREATE TABLE source_config (
  id INTEGER PRIMARY KEY, profile_id INT NOT NULL REFERENCES profile(id),
  platform TEXT NOT NULL, slug TEXT NOT NULL, name TEXT NOT NULL,
  method TEXT NOT NULL, rules JSON NOT NULL DEFAULT '{}');

-- global caches -------------------------------------------------------------
CREATE TABLE post (
  id TEXT PRIMARY KEY,                  -- 'fbpost:1234' — canonical across scrapers
  source TEXT, url TEXT, group_name TEXT,
  author_name TEXT, author_url TEXT, posted_at TEXT, text TEXT NOT NULL,
  first_seen TIMESTAMP NOT NULL);

CREATE TABLE extraction (               -- LLM pass 1: intent + dates
  post_id TEXT PRIMARY KEY REFERENCES post(id),
  is_seeking BOOL, start_date DATE, end_date DATE, date_text TEXT,
  budget TEXT, confidence TEXT, model TEXT, error TEXT,
  extracted_at TIMESTAMP NOT NULL);

CREATE TABLE enrichment (               -- LLM pass 2: household fit, seekers only
  post_id TEXT PRIMARY KEY REFERENCES post(id),
  people_in_one_room INT, wants_multiple_rooms BOOL, gender TEXT, group_size INT,
  model TEXT, enriched_at TIMESTAMP NOT NULL);

-- per profile ---------------------------------------------------------------
CREATE TABLE candidate (                -- a person, not a post
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id),
  person_key TEXT NOT NULL,             -- lower(name) + wants_start + wants_end
  post_id TEXT NOT NULL REFERENCES post(id),   -- newest post that surfaced them
  also_posted_in JSON NOT NULL DEFAULT '[]',   -- their other sightings
  tier TEXT, tier_reason TEXT, fit TEXT, days_covered INT,
  wants_start DATE, wants_end DATE,
  status TEXT NOT NULL DEFAULT 'new', draft TEXT,
  first_seen TIMESTAMP NOT NULL,
  UNIQUE(profile_id, person_key));

CREATE TABLE outreach_action (          -- append-only log; used from M3
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id),
  candidate_id INT REFERENCES candidate(id),
  kind TEXT NOT NULL,                   -- dm | comment | listing_post
  text TEXT, status TEXT NOT NULL,      -- proposed|sent|verified|failed|blocked
  sent_at TIMESTAMP, verified_at TIMESTAMP, error TEXT);

CREATE TABLE my_post (                  -- the user's own listing, per group; M4
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id),
  source TEXT, group_name TEXT, permalink TEXT,
  status TEXT NOT NULL,                 -- live|pending_approval|planned|blocked
  blocked_reason TEXT, posted_at TIMESTAMP);

CREATE TABLE schema_version (version INT NOT NULL);
```

Three boundaries carry weight:

**`post` is not `candidate`.** A post is a document; a candidate is a person. The same
human cross-posts to six groups and should occupy one row, not six — hence `person_key`
keyed on name plus requested dates rather than on the post id, with `also_posted_in`
retaining the other sightings.

**`extraction` and `enrichment` are separate from `post` and from each other.** A
re-scrape never re-pays for parsing, swapping models later doesn't touch scraped text,
and the second pass (which runs on seekers only) can never redo date work.

**`outreach_action` is a log, not a status column.** One candidate can be DM'd, then
commented on, then followed up: three rows, one candidate. In autopilot this log *is*
the rate limiter — "how many DMs in the last 24 hours" is a `COUNT(*)` over it, which a
`last_contacted` column could not express.

Schema for `outreach_action` and `my_post` lands in M1 even though nothing writes to
them until M3/M4, so later migrations don't have to restructure live databases.

## 7. Module contracts

```python
# sources/base.py
class Source(Protocol):
    name: str
    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]: ...

# llm/base.py
class LLMProvider(Protocol):
    name: str
    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel: ...
    def health(self) -> ProviderHealth: ...

# extract/
def run_extraction(posts: list[Post], provider: LLMProvider, batch: int = 12) -> list[Extraction]
def run_enrichment(seekers: list[Post], provider: LLMProvider) -> list[Enrichment]

# match/  — pure functions, no I/O
def classify(start, end, w_start, w_end) -> tuple[Fit | None, int]
def tier_for(cand: CandidateFacts, c: Constraints, window_days: int) -> tuple[str, str]
def dedupe_people(cands: list[Candidate]) -> list[Candidate]
def rank(extractions, enrichments, posts, profile) -> list[Candidate]
def coverage(cands, window, max_split) -> CoveragePlan
```

`match` is deliberately I/O-free. Every interesting rule in the product lives there and
is therefore directly testable without a database, a network, or a model.

## 8. LLM providers

The `claude -p` subprocess is replaced by a provider abstraction with four
implementations:

| Provider | Configuration | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | Default. `claude-haiku-4-5` for extraction. |
| `openai` | `OPENAI_API_KEY` | For users already holding an OpenAI key. |
| `ollama` | local daemon URL | No key, no cost, no data leaving the machine. |
| `claude-cli` | existing Claude Code install | Ports the prototype's subprocess path; free for Claude Code subscribers. |

`claude-haiku-4-5` is the documented default for extraction, carried forward from the
prototype's own `extract_model: haiku` setting, and configurable per profile. At
$1/$5 per million tokens and roughly 500 input tokens per post, a full 350-post
backfill costs well under a dollar. Extraction is a narrow classification task where
the prototype demonstrated this class of model is sufficient; users who want a stronger
model can set one.

The Anthropic provider uses **structured outputs** — `client.messages.parse()` against a
Pydantic schema — which replaces the prototype's `text.find("[") / text.rfind("]")`
substring scraping (`reference/pipeline/extract.py:57-62`) with schema validation at the
API layer. Providers without native structured output (Ollama, `claude-cli`) fall back
to JSON-mode prompting plus Pydantic validation behind the same interface.

Prompt caching is not used: the prompts are far below Haiku 4.5's 4,096-token minimum
cacheable prefix, so a `cache_control` breakpoint would silently never produce a hit.

## 9. Ported logic, and three defects it carries

The following move across essentially unchanged: `canonical_pid` and `normalize`
(`scrape.py:35-77`), `classify` window-overlap (`filter_rank.py:72-91`), `tier_for`
(now taking `Constraints`), person dedupe (`filter_rank.py:171-180`), the Messenger
emoticon sanitizer (`filter_rank.py:116-123`), the Notion comma-stripping and
merge-don't-replace select handling (`notion_push.py`), and the batch-bisect recovery
in extraction.

Batch-bisect and structured outputs are complementary, not redundant: structured
outputs remove *parsing* failures, while bisect still isolates a single post that
provokes a refusal, a timeout, or an oversized request out of a batch of twelve.

Porting surfaced three real defects that block generalization. All three are fixed in M1.

**1. The extraction prompt hardcodes the current date.**
`reference/pipeline/extract.py:21-23` embeds `"Today's date is 2026-08-11."` and
`"Labor Day 2026 is September 7."` For any other user — or for the same user next year —
every relative phrase ("late August", "through Labor Day") silently resolves to the
wrong year. Fixed by computing the reference date at call time and deriving US holidays
from the run year rather than stating them as literals.

**2. Coverage only searches pairs.**
`filter_rank.py:231` enumerates `combinations(partials, 2)`. The prototype's own
writeup records that the outcome which actually filled the window was a *three*-person
split — meaning the tool could not have surfaced the arrangement its author found by
hand. M1 replaces pair enumeration with greedy interval set-cover up to
`window.max_split` seekers, defaulting to 3.

**3. Pair search is quadratic with per-day set construction.**
The same loop builds a `set` of `date` objects day by day for every pair. At 125
candidates and a 22-day window that is tolerable; at 500 candidates it is not. Replaced
with interval arithmetic, which is both faster and simpler than the code it removes.

## 10. Failure behavior

Ported from the prototype, which learned these the hard way:

- A source that fails logs the error and the run continues with the remaining sources;
  one broken scraper never costs a whole run.
- An LLM batch that fails bisects down to the single offending post, records it in
  `extraction.error`, and proceeds. One malformed post cannot sink a batch of twelve.
- Extraction is never repeated for a post id that already has a row.
- Posts with no date-like token are cheaply pre-filtered before reaching the model
  (`DATE_HINT`, `extract.py:13-17`) and recorded as non-seeking.

New in M1:

- `sublease doctor` verifies, before a run can waste twenty minutes: the configured LLM
  provider answers a trivial request, `forage` is installed and its Facebook session is
  still valid, the database is writable, and the profile validates.
- SQLite runs in WAL mode with a single writer; migrations are forward-only and applied
  at startup with the applied version recorded in `schema_version`.

## 11. Testing

`match` is entirely pure functions, which makes it the natural home for test effort and
a good fit for test-driven development:

| Area | Test approach |
|---|---|
| `classify`, `tier_for`, dedupe, coverage | Table-driven unit tests over date ranges, occupancy, and constraint permutations |
| Sanitizers (`8)` → `8 )`, comma-stripping) | Direct assertions on known-bad inputs |
| `canonical_pid`, `normalize` | Fixtures from both scrapers producing one id for one post |
| Extraction and enrichment | Fake provider returning canned structured output; no network in the suite |
| Fuzzy date phrases | Golden table (`"through Labor Day"`, `"late August"`, `"the month of August"`) evaluated against a fixed reference date |
| End-to-end | `fixtures/posts.json` → ranked candidates, asserted as a golden file |
| Regression | The original author's profile and constraints must reproduce their live ranking |

Provider implementations get thin contract tests against a recorded response; no test
in the suite makes a network call or touches Facebook.

## 12. CLI surface for M1

```
sublease init            interactive profile creation (precursor to the M2 wizard)
sublease run             scrape → extract → enrich → match → write candidates
    --source X           limit to one configured source
    --days N             override the scrape lookback
    --fixtures           run the whole pipeline on synthetic posts, no Facebook
    --dry-run            report what would change without writing
sublease candidates      list ranked candidates; --tier, --new, --csv
sublease coverage        best single seekers and best combinations
sublease doctor          verify providers, scraper, session, database, profile
```

## 13. Milestones after M1

| Milestone | Contents |
|---|---|
| **M2** | FastAPI JSON API, React SPA, onboarding wizard, candidate board, coverage view |
| **M3** | Outreach queue; guardrails module *first*, then `ManualExecutor` and `BrowserExecutor`; autopilot behind its disclosure |
| **M4** | Notion mirror, one-line installer, in-process scheduler, public documentation |

M3 builds the guardrail module — data-driven rate limits, message variation,
checkpoint and CAPTCHA detection with immediate halt and notification, post-action
verification by re-reading the page, jittered daytime cadence, dry-run, kill switch,
and an append-only audit log — before either executor exists, so no commit in the
repository's history can run automation unguarded.

## 14. Assumptions

Stated explicitly so they can be corrected rather than discovered later:

1. **Multi-profile is supported but not emphasized.** Most installs will hold one
   profile. Carrying `profile_id` from the start costs almost nothing and covers
   subletting two rooms, or helping a friend, without a migration.
2. **`allow_split` defaults to on.** It is a superset: with it off the user simply sees
   single seekers. The prototype's own successful outcome was a split.
3. **Facebook is the only platform in M1.** The `Source` protocol exists so Reddit
   (which has a real API) or a university board can be added later as an adapter, not a
   rewrite.
4. **Apify support is ported** despite being a paid third party, because it is
   roughly twenty lines and it is the only path to public groups the user has not joined.
5. **The database is not encrypted at rest.** It holds scraped personal information
   about third parties and lives on the user's own machine, alongside their other
   personal files. M4's documentation must state plainly what is stored and recommend a
   retention window; a purge command is a candidate for M4.
