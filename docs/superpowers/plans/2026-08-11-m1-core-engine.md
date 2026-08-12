# Sublease Agent M1 — Core Engine + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-user `sublease-finder` prototype into a config-driven, tested Python package where any user can define their own sublease profile and get a correctly ranked list of candidate subletters from their own Facebook groups.

**Architecture:** A layered Python package. `profile` holds the user's config as Pydantic models; `store` persists to SQLite; `sources` fetch posts behind a common protocol; `llm` wraps four interchangeable model providers; `extract` runs two cached LLM passes; `match` is pure functions (window overlap, tiering, dedupe, coverage, drafts) with no I/O; `pipeline` orchestrates; `cli` is the user surface. Logic that survived production in the prototype is ported near-verbatim, with its hardcoded constants lifted onto the profile.

**Tech Stack:** Python 3.12, uv, Pydantic v2, SQLite (stdlib `sqlite3`), Anthropic Python SDK, httpx, Typer, Rich, pytest, ruff.

## Global Constraints

- **Python 3.12+.** The prototype's venv is CPython 3.12; do not use 3.13-only syntax.
- **Reference implementation** lives at `reference/` (gitignored). Port from it; do not import it.
- **No network in the test suite.** Every test uses `FakeProvider` or fixture files. No test touches Facebook, Anthropic, or any HTTP endpoint.
- **Extraction model default is `claude-haiku-4-5`**, carried forward from the prototype's `extract_model: haiku`. Exact string, no date suffix.
- **Haiku 4.5 takes no `thinking` and no `output_config.effort` parameter** — `effort` errors on that model. Extraction requests pass neither.
- **`SUBLEASE_HOME`** env var, default `~/.sublease`. Database at `$SUBLEASE_HOME/sublease.db`. (This refines the spec's `data/sublease.db`, which was cwd-relative and wrong for a globally installed CLI.)
- **Gender is used only when self-stated** in a post. Never inferred from a name or photo. Enforced in the enrichment prompt and asserted in tests.
- **Every module under `sublease/match/` is pure** — no database, no network, no clock reads. Callers pass dates in.
- **Commit after every task.** Conventional commit prefixes (`feat:`, `test:`, `fix:`, `chore:`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, deps, pytest/ruff config |
| `sublease/errors.py` | Exception hierarchy |
| `sublease/paths.py` | `SUBLEASE_HOME` resolution |
| `sublease/profile/models.py` | `Place`, `Window`, `Price`, `Constraints`, `Templates`, `SourceConfig`, `Profile` |
| `sublease/store/schema.py` | DDL statements, `MIGRATIONS` list |
| `sublease/store/db.py` | Connection, WAL, `migrate()` |
| `sublease/store/repositories.py` | `ProfileRepo`, `PostRepo`, `ExtractionRepo`, `EnrichmentRepo`, `CandidateRepo` |
| `sublease/sources/base.py` | `RawPost`, `Source` protocol |
| `sublease/sources/normalize.py` | `canonical_pid`, `clean_author_url`, `normalize`, `load_records` |
| `sublease/sources/fixtures.py` | `FixtureSource` |
| `sublease/sources/forage.py` | `ForageFacebookSource` |
| `sublease/sources/apify.py` | `ApifySource` |
| `sublease/llm/base.py` | `LLMProvider` protocol, `ProviderHealth` |
| `sublease/llm/anthropic_provider.py` | Default provider, structured outputs |
| `sublease/llm/openai_provider.py` | OpenAI via httpx |
| `sublease/llm/ollama_provider.py` | Local Ollama via httpx |
| `sublease/llm/claude_cli_provider.py` | `claude -p` subprocess (ported) |
| `sublease/llm/registry.py` | `get_provider(name, settings)` |
| `sublease/extract/schemas.py` | LLM-facing Pydantic schemas |
| `sublease/extract/dates.py` | `labor_day`, `date_hint_matches` |
| `sublease/extract/prompts.py` | Prompt builders taking a reference date |
| `sublease/extract/runner.py` | Batching, bisect recovery, cache checks |
| `sublease/match/types.py` | `Fit`, `CandidateFacts`, `Candidate`, `CoveragePlan` |
| `sublease/match/window.py` | `classify()` |
| `sublease/match/tiering.py` | `tier_for()` |
| `sublease/match/dedupe.py` | `dedupe_people()` |
| `sublease/match/drafts.py` | `sanitize_for_messenger()`, `build_draft()` |
| `sublease/match/coverage.py` | Interval set-cover |
| `sublease/match/ranking.py` | `rank()` |
| `sublease/pipeline.py` | `run_pipeline()` |
| `sublease/cli/main.py` | Typer app: `init run candidates coverage doctor` |
| `tests/fakes.py` | `FakeProvider` + canned fixture extractions |

---

## Task 1: Project scaffolding and toolchain

**Files:**
- Create: `pyproject.toml`, `sublease/__init__.py`, `sublease/errors.py`, `sublease/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing
- Produces: `sublease.errors.SubleaseError`, `ConfigError`, `SourceError`, `ProviderError`, `StoreError`; `sublease.paths.sublease_home() -> Path`, `db_path() -> Path`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "sublease-agent"
version = "0.1.0"
description = "Finds subletters for your place across the groups where they already post"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.7",
    "anthropic>=0.40",
    "httpx>=0.27",
    "typer>=0.12",
    "rich>=13.7",
]

[project.scripts]
sublease = "sublease.cli.main:app"

[dependency-groups]
dev = ["pytest>=8.2", "pytest-cov>=5.0", "ruff>=0.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["sublease"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_paths.py
from pathlib import Path
from sublease.paths import sublease_home, db_path


def test_home_defaults_to_dot_sublease(monkeypatch):
    monkeypatch.delenv("SUBLEASE_HOME", raising=False)
    assert sublease_home() == Path.home() / ".sublease"


def test_home_honors_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    assert sublease_home() == tmp_path


def test_db_path_sits_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLEASE_HOME", str(tmp_path))
    assert db_path() == tmp_path / "sublease.db"


def test_home_is_created_on_demand(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "home"
    monkeypatch.setenv("SUBLEASE_HOME", str(target))
    assert sublease_home(create=True).is_dir()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease'`

- [ ] **Step 4: Write `sublease/errors.py`**

```python
"""Exception hierarchy. Every failure the CLI reports inherits from SubleaseError."""


class SubleaseError(Exception):
    """Base for every error this package raises deliberately."""


class ConfigError(SubleaseError):
    """The user's profile or environment is missing or invalid."""


class StoreError(SubleaseError):
    """The database could not be opened, migrated, or written."""


class SourceError(SubleaseError):
    """A platform source failed to fetch. Never fatal to a run."""


class ProviderError(SubleaseError):
    """An LLM provider was unreachable or returned unusable output."""
```

- [ ] **Step 5: Write `sublease/paths.py`**

```python
"""Where this tool keeps its data.

A globally installed CLI must not write next to the current working directory,
so everything lives under SUBLEASE_HOME (default ~/.sublease).
"""
import os
from pathlib import Path

ENV_VAR = "SUBLEASE_HOME"
DEFAULT_DIR = ".sublease"


def sublease_home(create: bool = False) -> Path:
    raw = os.environ.get(ENV_VAR)
    home = Path(raw).expanduser() if raw else Path.home() / DEFAULT_DIR
    if create:
        home.mkdir(parents=True, exist_ok=True)
    return home


def db_path() -> Path:
    return sublease_home() / "sublease.db"
```

- [ ] **Step 6: Write `sublease/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_paths.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml sublease/ tests/ uv.lock
git commit -m "chore: scaffold package, error hierarchy, and data paths"
```

---

## Task 2: Profile models

**Files:**
- Create: `sublease/profile/__init__.py`, `sublease/profile/models.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `sublease.errors.ConfigError`
- Produces: `Place`, `Window`, `Price`, `Constraints`, `Templates`, `SourceConfig`, `Profile`. Key fields other tasks rely on: `Window.start: date`, `Window.end: date`, `Window.days: int` (property), `Window.allow_split: bool`, `Window.max_split: int`; `Constraints.max_people_per_room: int`, `.multi_room_seekers_ok: bool`, `.gender_preference: Literal["male","female"] | None`, `.tier_a_coverage: float`, `.tier_b_coverage: float`; `Templates.outreach_message: str`, `.listing_post: str`; `SourceConfig.platform/slug/name/method: str`, `.rules: dict`; `Profile.id: int | None`, `.name: str`, `.window`, `.constraints`, `.templates`, `.sources: list[SourceConfig]`, `.price`, `.place`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile.py
from datetime import date
import pytest
from pydantic import ValidationError
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)


def make_window(**kw):
    base = {"start": date(2026, 8, 18), "end": date(2026, 9, 8)}
    return Window(**{**base, **kw})


def test_window_days_is_inclusive():
    assert make_window().days == 22


def test_window_rejects_end_before_start():
    with pytest.raises(ValidationError):
        Window(start=date(2026, 9, 8), end=date(2026, 8, 18))


def test_window_defaults_allow_split_on_with_max_three():
    w = make_window()
    assert w.allow_split is True
    assert w.max_split == 3


def test_max_split_is_forced_to_one_when_split_disallowed():
    assert make_window(allow_split=False, max_split=3).max_split == 1


def test_price_derives_total_from_nightly():
    assert Price(nightly=100).total_for(22) == 2200


def test_price_derives_nightly_from_total():
    assert Price(total=2200).nightly_for(22) == 100


def test_price_requires_one_of_nightly_or_total():
    with pytest.raises(ValidationError):
        Price()


def test_constraint_defaults_match_the_prototype():
    c = Constraints()
    assert c.max_people_per_room == 1
    assert c.multi_room_seekers_ok is True
    assert c.gender_preference is None
    assert (c.tier_a_coverage, c.tier_b_coverage) == (0.90, 0.60)


def test_tier_b_coverage_must_not_exceed_tier_a():
    with pytest.raises(ValidationError):
        Constraints(tier_a_coverage=0.5, tier_b_coverage=0.9)


def test_template_placeholders_are_validated():
    with pytest.raises(ValidationError):
        Templates(outreach_message="Hi {nickname}", listing_post="x")


def test_templates_accept_the_supported_placeholders():
    t = Templates(
        outreach_message="Hi {first_name}, saw your post in {group} for {their_dates}",
        listing_post="Room available.",
    )
    assert "{first_name}" in t.outreach_message


def test_profile_round_trips_through_json():
    p = Profile(
        name="East Village room",
        place=Place(neighborhood="East Village", unit_type="room", bedrooms=1),
        window=make_window(),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="Room."),
        sources=[SourceConfig(platform="facebook", slug="nycsublets",
                              name="NYC Sublets", method="forage")],
    )
    assert Profile.model_validate_json(p.model_dump_json()) == p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.profile'`

- [ ] **Step 3: Write `sublease/profile/models.py`**

```python
"""The user's sublease, as data.

Everything the prototype hardcoded — the window, the household rules, the copy,
the group list — is a field here.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

UnitType = Literal["room", "whole_unit"]
BathType = Literal["shared", "private"]
Gender = Literal["male", "female"]

# Placeholders build_draft() knows how to substitute.
ALLOWED_PLACEHOLDERS = {"first_name", "their_dates", "group"}
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


class Place(BaseModel):
    neighborhood: str
    unit_type: UnitType = "room"
    bedrooms: int = 1
    bath: BathType = "shared"
    furnished: bool = True
    amenities: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)


class Window(BaseModel):
    start: date
    end: date
    flexible: bool = False
    allow_split: bool = True
    max_split: int = 3

    @property
    def days(self) -> int:
        """Inclusive length. Aug 18 - Sep 8 is 22 days, not 21."""
        return (self.end - self.start).days + 1

    @model_validator(mode="after")
    def _check(self) -> Window:
        if self.end < self.start:
            raise ValueError("window.end must not precede window.start")
        if not self.allow_split:
            object.__setattr__(self, "max_split", 1)
        elif self.max_split < 1:
            raise ValueError("window.max_split must be at least 1")
        return self


class Price(BaseModel):
    nightly: float | None = None
    total: float | None = None

    @model_validator(mode="after")
    def _one_is_required(self) -> Price:
        if self.nightly is None and self.total is None:
            raise ValueError("price needs either nightly or total")
        return self

    def total_for(self, days: int) -> float:
        return self.total if self.total is not None else self.nightly * days

    def nightly_for(self, days: int) -> float:
        return self.nightly if self.nightly is not None else self.total / days


class Constraints(BaseModel):
    """Household rules. Ported from reference/pipeline/filter_rank.py:33-60."""

    max_people_per_room: int = 1
    multi_room_seekers_ok: bool = True
    gender_preference: Gender | None = None
    tier_a_coverage: float = 0.90
    tier_b_coverage: float = 0.60
    pets_ok: bool = True
    deposit_terms: str | None = None

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> Constraints:
        if self.tier_b_coverage > self.tier_a_coverage:
            raise ValueError("tier_b_coverage must not exceed tier_a_coverage")
        return self


class Templates(BaseModel):
    outreach_message: str
    listing_post: str

    @model_validator(mode="after")
    def _known_placeholders_only(self) -> Templates:
        found = set(_PLACEHOLDER_RE.findall(self.outreach_message))
        unknown = found - ALLOWED_PLACEHOLDERS
        if unknown:
            raise ValueError(
                f"unknown placeholder(s) {sorted(unknown)}; "
                f"supported: {sorted(ALLOWED_PLACEHOLDERS)}"
            )
        return self


class SourceConfig(BaseModel):
    platform: str = "facebook"
    slug: str
    name: str
    method: str = "forage"
    rules: dict = Field(default_factory=dict)


class Profile(BaseModel):
    id: int | None = None
    name: str
    place: Place
    window: Window
    price: Price
    constraints: Constraints = Field(default_factory=Constraints)
    templates: Templates
    sources: list[SourceConfig] = Field(default_factory=list)
```

- [ ] **Step 4: Write `sublease/profile/__init__.py`**

```python
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)

__all__ = [
    "Constraints", "Place", "Price", "Profile", "SourceConfig", "Templates", "Window",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_profile.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add sublease/profile tests/test_profile.py
git commit -m "feat: profile models replacing the prototype's hardcoded config"
```

---

## Task 3: Database schema, migrations, and connection

**Files:**
- Create: `sublease/store/__init__.py`, `sublease/store/schema.py`, `sublease/store/db.py`
- Test: `tests/test_store_db.py`

**Interfaces:**
- Consumes: `sublease.errors.StoreError`, `sublease.paths.db_path`
- Produces: `sublease.store.db.connect(path: Path | None = None) -> sqlite3.Connection`, `migrate(conn) -> int` (returns applied version), `current_version(conn) -> int`; `sublease.store.schema.MIGRATIONS: list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store_db.py
import sqlite3
import pytest
from sublease.store.db import connect, current_version, migrate
from sublease.store.schema import MIGRATIONS

TABLES = {
    "profile", "source_config", "post", "extraction", "enrichment",
    "candidate", "outreach_action", "my_post", "schema_version",
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_migrate_creates_every_table(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    assert TABLES <= table_names(conn)


def test_migrate_records_the_version(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    assert current_version(conn) == len(MIGRATIONS)


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    conn = connect(path)
    migrate(conn)
    migrate(conn)
    assert current_version(conn) == len(MIGRATIONS)


def test_wal_mode_is_enabled(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_foreign_keys_are_enforced(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO candidate (profile_id, person_key, post_id, first_seen) "
            "VALUES (999, 'nobody', 'fbpost:1', '2026-08-11')"
        )


def test_rows_come_back_keyed_by_column_name(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == len(MIGRATIONS)


def test_candidate_person_key_is_unique_per_profile(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO profile (id, name, place, window_start, window_end, price, "
        "constraints, templates) VALUES (1,'p','{}','2026-08-18','2026-09-08','{}','{}','{}')"
    )
    conn.execute(
        "INSERT INTO post (id, text, first_seen) VALUES ('fbpost:1','hi','2026-08-11')"
    )
    args = (1, "emma|2026-08-18|2026-09-08", "fbpost:1", "2026-08-11")
    sql = ("INSERT INTO candidate (profile_id, person_key, post_id, first_seen) "
           "VALUES (?,?,?,?)")
    conn.execute(sql, args)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.store'`

- [ ] **Step 3: Write `sublease/store/schema.py`**

```python
"""Schema as an ordered list of forward-only migrations.

Never edit an existing entry — append a new one. `outreach_action` and `my_post`
are created now although nothing writes to them until M3/M4, so those milestones
never have to restructure a live database.
"""

_V1 = """
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  place JSON NOT NULL,
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  flexible BOOL NOT NULL DEFAULT 0,
  allow_split BOOL NOT NULL DEFAULT 1,
  max_split INT NOT NULL DEFAULT 3,
  price JSON NOT NULL,
  constraints JSON NOT NULL,
  templates JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS source_config (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  method TEXT NOT NULL,
  rules JSON NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS post (
  id TEXT PRIMARY KEY,
  source TEXT,
  url TEXT,
  group_name TEXT,
  author_name TEXT,
  author_url TEXT,
  posted_at TEXT,
  text TEXT NOT NULL,
  first_seen TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction (
  post_id TEXT PRIMARY KEY REFERENCES post(id) ON DELETE CASCADE,
  is_seeking BOOL,
  start_date DATE,
  end_date DATE,
  date_text TEXT,
  budget TEXT,
  confidence TEXT,
  model TEXT,
  error TEXT,
  extracted_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS enrichment (
  post_id TEXT PRIMARY KEY REFERENCES post(id) ON DELETE CASCADE,
  people_in_one_room INT,
  wants_multiple_rooms BOOL,
  gender TEXT,
  group_size INT,
  model TEXT,
  enriched_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  person_key TEXT NOT NULL,
  post_id TEXT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  also_posted_in JSON NOT NULL DEFAULT '[]',
  tier TEXT,
  tier_reason TEXT,
  fit TEXT,
  days_covered INT,
  wants_start DATE,
  wants_end DATE,
  status TEXT NOT NULL DEFAULT 'new',
  draft TEXT,
  first_seen TIMESTAMP NOT NULL,
  UNIQUE(profile_id, person_key)
);

CREATE TABLE IF NOT EXISTS outreach_action (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  candidate_id INT REFERENCES candidate(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  text TEXT,
  status TEXT NOT NULL,
  sent_at TIMESTAMP,
  verified_at TIMESTAMP,
  error TEXT
);

CREATE TABLE IF NOT EXISTS my_post (
  id INTEGER PRIMARY KEY,
  profile_id INT NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  source TEXT,
  group_name TEXT,
  permalink TEXT,
  status TEXT NOT NULL,
  blocked_reason TEXT,
  posted_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidate_profile_tier
  ON candidate(profile_id, tier, days_covered DESC);
CREATE INDEX IF NOT EXISTS idx_outreach_profile_kind_sent
  ON outreach_action(profile_id, kind, sent_at);
"""

MIGRATIONS: list[str] = [_V1]
```

- [ ] **Step 4: Write `sublease/store/db.py`**

```python
"""SQLite connection and forward-only migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sublease.errors import StoreError
from sublease.paths import db_path, sublease_home
from sublease.store.schema import MIGRATIONS


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is None:
        sublease_home(create=True)
        path = db_path()
    try:
        conn = sqlite3.connect(path, isolation_level=None)
    except sqlite3.Error as exc:
        raise StoreError(f"cannot open database at {path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    got = conn.execute("SELECT version FROM schema_version").fetchone()
    return got["version"] if got else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the recorded version. Returns the new version."""
    version = current_version(conn)
    for index, script in enumerate(MIGRATIONS, start=1):
        if index <= version:
            continue
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            raise StoreError(f"migration {index} failed: {exc}") from exc
        version = index
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    return version
```

- [ ] **Step 5: Write `sublease/store/__init__.py`**

```python
from sublease.store.db import connect, current_version, migrate

__all__ = ["connect", "current_version", "migrate"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_store_db.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add sublease/store tests/test_store_db.py
git commit -m "feat: SQLite schema, WAL connection, and forward-only migrations"
```

---

## Task 4: Repositories

**Files:**
- Create: `sublease/store/repositories.py`
- Modify: `sublease/store/__init__.py`
- Test: `tests/test_store_repositories.py`

**Interfaces:**
- Consumes: Task 2 models, Task 3 `connect`/`migrate`
- Produces:
  - `ProfileRepo(conn)`: `.save(profile) -> Profile` (assigns `id`, replaces its `source_config` rows), `.get(profile_id) -> Profile | None`, `.list() -> list[Profile]`
  - `PostRepo(conn)`: `.upsert_many(posts: list[RawPost]) -> int` (returns count of newly inserted), `.get_all() -> list[dict]`, `.get_many(ids) -> dict[str, dict]`, `.ids_without_extraction() -> list[str]`
  - `ExtractionRepo(conn)`: `.save_many(rows: list[dict]) -> None`, `.get_all() -> list[dict]`, `.seeker_ids() -> list[str]`, `.done_ids() -> set[str]`
  - `EnrichmentRepo(conn)`: `.save_many(rows) -> None`, `.by_post_id() -> dict[str, dict]`, `.done_ids() -> set[str]`
  - `CandidateRepo(conn)`: `.sync(profile_id, candidates) -> tuple[int, int]` (new, updated — never clobbers `status`), `.list(profile_id, tier=None, new_only=False) -> list[dict]`

Row dicts use the column names from Task 3 verbatim.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store_repositories.py
from datetime import date, datetime
import pytest
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)
from sublease.store.db import connect, migrate
from sublease.store.repositories import (
    CandidateRepo, EnrichmentRepo, ExtractionRepo, PostRepo, ProfileRepo,
)

NOW = datetime(2026, 8, 11, 9, 0, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def a_profile(**kw):
    base = dict(
        name="East Village room",
        place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="Room."),
        sources=[SourceConfig(slug="nycsublets", name="NYC Sublets")],
    )
    return Profile(**{**base, **kw})


def a_post(pid="fbpost:1", **kw):
    base = dict(id=pid, source="facebook", url=f"https://fb.com/{pid}",
                group_name="G", author_name="Emma", author_url="https://fb.com/e",
                posted_at="2026-08-09", text="looking for a sublet aug 18 - sep 8")
    return {**base, **kw}


def test_profile_round_trips_with_its_sources(conn):
    saved = ProfileRepo(conn).save(a_profile())
    assert saved.id is not None
    loaded = ProfileRepo(conn).get(saved.id)
    assert loaded == saved
    assert loaded.sources[0].slug == "nycsublets"


def test_saving_an_existing_profile_replaces_its_sources(conn):
    repo = ProfileRepo(conn)
    saved = repo.save(a_profile())
    saved.sources = [SourceConfig(slug="gypsyhousing", name="Ghostlight")]
    repo.save(saved)
    assert [s.slug for s in repo.get(saved.id).sources] == ["gypsyhousing"]


def test_post_upsert_reports_only_new_rows(conn):
    repo = PostRepo(conn)
    assert repo.upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW) == 2
    assert repo.upsert_many([a_post("fbpost:2"), a_post("fbpost:3")], now=NOW) == 1


def test_post_upsert_preserves_the_original_first_seen(conn):
    repo = PostRepo(conn)
    repo.upsert_many([a_post()], now=NOW)
    repo.upsert_many([a_post(text="edited")], now=datetime(2026, 9, 1))
    row = repo.get_many(["fbpost:1"])["fbpost:1"]
    assert row["first_seen"].startswith("2026-08-11")


def test_ids_without_extraction_excludes_extracted_posts(conn):
    PostRepo(conn).upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW)
    ExtractionRepo(conn).save_many([
        {"post_id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-18",
         "end_date": "2026-09-08", "date_text": "aug 18 - sep 8", "budget": None,
         "confidence": "high", "model": "fake", "error": None},
    ], now=NOW)
    assert PostRepo(conn).ids_without_extraction() == ["fbpost:2"]


def test_seeker_ids_returns_only_seekers(conn):
    PostRepo(conn).upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW)
    ExtractionRepo(conn).save_many([
        {"post_id": "fbpost:1", "is_seeking": True, "model": "fake"},
        {"post_id": "fbpost:2", "is_seeking": False, "model": "fake"},
    ], now=NOW)
    assert ExtractionRepo(conn).seeker_ids() == ["fbpost:1"]


def test_enrichment_is_keyed_by_post_id(conn):
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    EnrichmentRepo(conn).save_many([
        {"post_id": "fbpost:1", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": "female", "group_size": 1, "model": "fake"},
    ], now=NOW)
    assert EnrichmentRepo(conn).by_post_id()["fbpost:1"]["gender"] == "female"


def a_candidate(**kw):
    base = dict(person_key="emma|2026-08-18|2026-09-08", post_id="fbpost:1",
                also_posted_in=[], tier="A", tier_reason="covers 22/22 days",
                fit="full-window", days_covered=22, wants_start="2026-08-18",
                wants_end="2026-09-08", draft="Hi Emma")
    return {**base, **kw}


def test_candidate_sync_inserts_then_updates(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    repo = CandidateRepo(conn)
    assert repo.sync(pid, [a_candidate()], now=NOW) == (1, 0)
    assert repo.sync(pid, [a_candidate(tier="B")], now=NOW) == (0, 1)
    assert repo.list(pid)[0]["tier"] == "B"


def test_candidate_sync_never_clobbers_a_human_edited_status(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    repo = CandidateRepo(conn)
    repo.sync(pid, [a_candidate()], now=NOW)
    conn.execute("UPDATE candidate SET status='replied'")
    repo.sync(pid, [a_candidate(tier="C")], now=NOW)
    row = repo.list(pid)[0]
    assert (row["status"], row["tier"]) == ("replied", "C")


def test_candidate_list_filters_by_tier(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW)
    CandidateRepo(conn).sync(pid, [
        a_candidate(),
        a_candidate(person_key="ivan|x|y", post_id="fbpost:2", tier="C"),
    ], now=NOW)
    assert [c["tier"] for c in CandidateRepo(conn).list(pid, tier="A")] == ["A"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store_repositories.py -v`
Expected: FAIL with `ImportError: cannot import name 'CandidateRepo'`

- [ ] **Step 3: Write `sublease/store/repositories.py`**

```python
"""Repositories. Each owns one table group and returns plain dicts or Profile objects.

The `sync` on CandidateRepo is add-or-update-but-never-clobber-status: the
prototype learned that lesson when a Notion select-option replace wiped 17
human-set statuses (reference/POSTING_SOP.md, lesson 3).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from sublease.profile.models import Profile, SourceConfig

POST_COLUMNS = ("id", "source", "url", "group_name", "author_name",
                "author_url", "posted_at", "text")
EXTRACTION_COLUMNS = ("post_id", "is_seeking", "start_date", "end_date",
                      "date_text", "budget", "confidence", "model", "error")
ENRICHMENT_COLUMNS = ("post_id", "people_in_one_room", "wants_multiple_rooms",
                      "gender", "group_size", "model")


def _now(now: datetime | None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


class ProfileRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, profile: Profile) -> Profile:
        row = (
            profile.name,
            profile.place.model_dump_json(),
            profile.window.start.isoformat(),
            profile.window.end.isoformat(),
            int(profile.window.flexible),
            int(profile.window.allow_split),
            profile.window.max_split,
            profile.price.model_dump_json(),
            profile.constraints.model_dump_json(),
            profile.templates.model_dump_json(),
        )
        if profile.id is None:
            cur = self.conn.execute(
                "INSERT INTO profile (name, place, window_start, window_end, flexible,"
                " allow_split, max_split, price, constraints, templates)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            profile.id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE profile SET name=?, place=?, window_start=?, window_end=?,"
                " flexible=?, allow_split=?, max_split=?, price=?, constraints=?,"
                " templates=? WHERE id=?", (*row, profile.id))
        self.conn.execute("DELETE FROM source_config WHERE profile_id=?", (profile.id,))
        self.conn.executemany(
            "INSERT INTO source_config (profile_id, platform, slug, name, method, rules)"
            " VALUES (?,?,?,?,?,?)",
            [(profile.id, s.platform, s.slug, s.name, s.method, json.dumps(s.rules))
             for s in profile.sources])
        return profile

    def get(self, profile_id: int) -> Profile | None:
        row = self.conn.execute("SELECT * FROM profile WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        sources = self.conn.execute(
            "SELECT * FROM source_config WHERE profile_id=? ORDER BY id", (profile_id,)
        ).fetchall()
        return Profile.model_validate({
            "id": row["id"],
            "name": row["name"],
            "place": json.loads(row["place"]),
            "window": {
                "start": row["window_start"], "end": row["window_end"],
                "flexible": bool(row["flexible"]),
                "allow_split": bool(row["allow_split"]),
                "max_split": row["max_split"],
            },
            "price": json.loads(row["price"]),
            "constraints": json.loads(row["constraints"]),
            "templates": json.loads(row["templates"]),
            "sources": [
                SourceConfig(platform=s["platform"], slug=s["slug"], name=s["name"],
                             method=s["method"], rules=json.loads(s["rules"]))
                for s in sources
            ],
        })

    def list(self) -> list[Profile]:
        ids = [r["id"] for r in self.conn.execute("SELECT id FROM profile ORDER BY id")]
        return [p for p in (self.get(i) for i in ids) if p is not None]


class PostRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_many(self, posts: list[dict], now: datetime | None = None) -> int:
        stamp = _now(now)
        inserted = 0
        for post in posts:
            values = tuple(post.get(c) for c in POST_COLUMNS)
            cur = self.conn.execute(
                "INSERT INTO post (id, source, url, group_name, author_name,"
                " author_url, posted_at, text, first_seen) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET"
                "   url=excluded.url, group_name=excluded.group_name,"
                "   author_name=excluded.author_name, author_url=excluded.author_url,"
                "   posted_at=excluded.posted_at, text=excluded.text",
                (*values, stamp))
            inserted += 1 if cur.rowcount == 1 and self._was_insert(post["id"], stamp) else 0
        return inserted

    def _was_insert(self, post_id: str, stamp: str) -> bool:
        row = self.conn.execute(
            "SELECT first_seen FROM post WHERE id=?", (post_id,)).fetchone()
        return row is not None and row["first_seen"] == stamp

    def get_many(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT * FROM post WHERE id IN ({marks})", ids)
        return {r["id"]: dict(r) for r in rows}

    def get_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM post ORDER BY id")]

    def ids_without_extraction(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT p.id FROM post p LEFT JOIN extraction e ON e.post_id = p.id"
            " WHERE e.post_id IS NULL ORDER BY p.id")
        return [r["id"] for r in rows]


class ExtractionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save_many(self, rows: list[dict], now: datetime | None = None) -> None:
        stamp = _now(now)
        self.conn.executemany(
            "INSERT INTO extraction (post_id, is_seeking, start_date, end_date,"
            " date_text, budget, confidence, model, error, extracted_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(post_id) DO NOTHING",
            [(*(r.get(c) for c in EXTRACTION_COLUMNS), stamp) for r in rows])

    def get_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM extraction")]

    def seeker_ids(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT post_id FROM extraction WHERE is_seeking=1 ORDER BY post_id")
        return [r["post_id"] for r in rows]

    def done_ids(self) -> set[str]:
        return {r["post_id"] for r in self.conn.execute("SELECT post_id FROM extraction")}


class EnrichmentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save_many(self, rows: list[dict], now: datetime | None = None) -> None:
        stamp = _now(now)
        self.conn.executemany(
            "INSERT INTO enrichment (post_id, people_in_one_room, wants_multiple_rooms,"
            " gender, group_size, model, enriched_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(post_id) DO NOTHING",
            [(*(r.get(c) for c in ENRICHMENT_COLUMNS), stamp) for r in rows])

    def by_post_id(self) -> dict[str, dict]:
        return {r["post_id"]: dict(r)
                for r in self.conn.execute("SELECT * FROM enrichment")}

    def done_ids(self) -> set[str]:
        return {r["post_id"] for r in self.conn.execute("SELECT post_id FROM enrichment")}


class CandidateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def sync(self, profile_id: int, candidates: list[dict],
             now: datetime | None = None) -> tuple[int, int]:
        """Add new candidates, refresh derived fields on known ones.

        `status` is never written on update — it belongs to the human.
        """
        stamp = _now(now)
        existing = {
            r["person_key"] for r in self.conn.execute(
                "SELECT person_key FROM candidate WHERE profile_id=?", (profile_id,))
        }
        new = updated = 0
        for c in candidates:
            payload = (c["post_id"], json.dumps(c.get("also_posted_in", [])),
                       c.get("tier"), c.get("tier_reason"), c.get("fit"),
                       c.get("days_covered"), c.get("wants_start"), c.get("wants_end"),
                       c.get("draft"))
            if c["person_key"] in existing:
                self.conn.execute(
                    "UPDATE candidate SET post_id=?, also_posted_in=?, tier=?,"
                    " tier_reason=?, fit=?, days_covered=?, wants_start=?, wants_end=?,"
                    " draft=? WHERE profile_id=? AND person_key=?",
                    (*payload, profile_id, c["person_key"]))
                updated += 1
            else:
                self.conn.execute(
                    "INSERT INTO candidate (profile_id, person_key, post_id,"
                    " also_posted_in, tier, tier_reason, fit, days_covered,"
                    " wants_start, wants_end, draft, first_seen)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (profile_id, c["person_key"], *payload, stamp))
                new += 1
        return new, updated

    def list(self, profile_id: int, tier: str | None = None,
             new_only: bool = False) -> list[dict]:
        sql = ["SELECT c.*, p.author_name, p.url AS post_url, p.group_name,"
               " p.author_url, p.text AS post_text FROM candidate c"
               " JOIN post p ON p.id = c.post_id WHERE c.profile_id=?"]
        args: list = [profile_id]
        if tier:
            sql.append("AND c.tier=?")
            args.append(tier)
        if new_only:
            sql.append("AND c.status='new'")
        sql.append("ORDER BY CASE c.tier WHEN 'A' THEN 0 WHEN 'B' THEN 1"
                   " WHEN 'C' THEN 2 ELSE 3 END, c.days_covered DESC")
        rows = self.conn.execute(" ".join(sql), args)
        out = []
        for r in rows:
            d = dict(r)
            d["also_posted_in"] = json.loads(d["also_posted_in"])
            out.append(d)
        return out
```

- [ ] **Step 4: Update `sublease/store/__init__.py`**

```python
from sublease.store.db import connect, current_version, migrate
from sublease.store.repositories import (
    CandidateRepo, EnrichmentRepo, ExtractionRepo, PostRepo, ProfileRepo,
)

__all__ = [
    "connect", "current_version", "migrate",
    "ProfileRepo", "PostRepo", "ExtractionRepo", "EnrichmentRepo", "CandidateRepo",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_store_repositories.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add sublease/store tests/test_store_repositories.py
git commit -m "feat: repositories with status-preserving candidate sync"
```

---

## Task 5: Post normalization

**Files:**
- Create: `sublease/sources/__init__.py`, `sublease/sources/base.py`, `sublease/sources/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: nothing
- Produces: `RawPost` (TypedDict with keys `id, source, url, group_name, author_name, author_url, posted_at, text`); `canonical_pid(url, fallback) -> str`; `clean_author_url(url) -> str | None`; `normalize(rec: dict, group_name: str, source: str, slug: str | None = None) -> RawPost`; `load_records(payload) -> list[dict]`; `Source` protocol with `.name: str` and `.fetch(cfg, since, limit) -> list[RawPost]`

Ported from `reference/pipeline/scrape.py:22-88`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_normalize.py
from sublease.sources.normalize import (
    canonical_pid, clean_author_url, load_records, normalize,
)


def test_permalink_and_posts_urls_yield_the_same_id():
    a = canonical_pid("https://facebook.com/groups/x/permalink/12345/", "fb")
    b = canonical_pid("https://facebook.com/groups/y/posts/12345", "fb")
    assert a == b == "fbpost:12345"


def test_story_fbid_query_param_is_recognised():
    assert canonical_pid("https://m.facebook.com/story.php?story_fbid=987&id=1",
                         "fb") == "fbpost:987"


def test_unparseable_url_falls_back():
    assert canonical_pid("https://example.com/thing", "fallback-id") == "fallback-id"


def test_missing_url_falls_back():
    assert canonical_pid(None, "fallback-id") == "fallback-id"


def test_author_url_is_made_absolute_and_stripped_of_tracking():
    assert clean_author_url("/emma?ref=group_x") == "https://www.facebook.com/emma"


def test_author_url_passthrough_for_absolute_urls():
    assert clean_author_url("https://facebook.com/emma") == "https://facebook.com/emma"


def test_author_url_handles_none():
    assert clean_author_url(None) is None


def test_normalize_maps_forage_shape():
    rec = {"text": "ISO a room", "url": "https://facebook.com/groups/g/posts/5",
           "author": {"name": "Emma", "url": "/emma"}, "time": "2026-08-09"}
    post = normalize(rec, "Fixture Group", "facebook")
    assert post["id"] == "fbpost:5"
    assert post["author_name"] == "Emma"
    assert post["author_url"] == "https://www.facebook.com/emma"
    assert post["group_name"] == "Fixture Group"
    assert post["posted_at"] == "2026-08-09"
    assert post["source"] == "facebook"


def test_normalize_maps_apify_shape():
    rec = {"postText": "ISO", "topLevelUrl": "https://facebook.com/groups/g/posts/6",
           "user": {"name": "Ivan", "profileUrl": "https://facebook.com/ivan"},
           "publishedTime": "2026-08-10"}
    post = normalize(rec, "G", "facebook")
    assert (post["id"], post["author_name"]) == ("fbpost:6", "Ivan")


def test_normalize_builds_a_url_from_slug_and_id_when_absent():
    rec = {"text": "ISO", "id": "77", "author": "Solo Author"}
    post = normalize(rec, "G", "facebook", slug="nycsublets")
    assert post["url"] == "https://www.facebook.com/groups/nycsublets/posts/77"
    assert post["id"] == "fbpost:77"


def test_normalize_hashes_when_there_is_no_url_or_id():
    rec = {"text": "ISO a room in august", "author": "Anon"}
    post = normalize(rec, "G", "facebook")
    assert post["id"].startswith("hash:")
    again = normalize(dict(rec), "G", "facebook")
    assert post["id"] == again["id"]


def test_load_records_unwraps_common_envelopes():
    assert load_records([{"a": 1}]) == [{"a": 1}]
    assert load_records({"posts": [{"a": 1}]}) == [{"a": 1}]
    assert load_records({"items": [{"a": 1}]}) == [{"a": 1}]
    assert load_records({"nothing": 1}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.sources'`

- [ ] **Step 3: Write `sublease/sources/base.py`**

```python
"""The contract every platform adapter implements."""
from __future__ import annotations

from datetime import date
from typing import Protocol, TypedDict

from sublease.profile.models import SourceConfig


class RawPost(TypedDict):
    id: str
    source: str
    url: str | None
    group_name: str
    author_name: str | None
    author_url: str | None
    posted_at: str | None
    text: str


class Source(Protocol):
    name: str

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        """Return posts from one configured source. Raises SourceError on failure."""
        ...
```

- [ ] **Step 4: Write `sublease/sources/normalize.py`**

```python
"""Turn each scraper's idiosyncratic record shape into one RawPost.

Ported from reference/pipeline/scrape.py:22-88. The canonical id matters:
two scrapers seeing the same Facebook post must produce the same string, or the
same person shows up twice (prototype lesson 7).
"""
from __future__ import annotations

import hashlib
import re

from sublease.sources.base import RawPost

FB_POST_NUM = re.compile(r"(?:permalink|posts)/(\d+)|story_fbid=(\d+)")

_TEXT_KEYS = ("text", "post_text", "content", "message", "postText")
_URL_KEYS = ("url", "post_url", "postUrl", "link", "topLevelUrl", "facebookUrl")
_AUTHOR_NAME_KEYS = ("name", "username", "title")
_AUTHOR_URL_KEYS = ("url", "profileUrl", "profile_url", "link")
_TIME_KEYS = ("time", "date", "timestamp", "posted_at", "creation_time",
              "date_posted", "publishedTime")


def _first(rec: dict, *keys):
    for key in keys:
        value = rec.get(key)
        if value:
            return value
    return None


def clean_author_url(url: str | None) -> str | None:
    if not url:
        return url
    url = url.split("?")[0]
    if url.startswith("/"):
        url = "https://www.facebook.com" + url
    return url


def canonical_pid(url: str | None, fallback: str) -> str:
    if url:
        match = FB_POST_NUM.search(url)
        if match:
            return f"fbpost:{match.group(1) or match.group(2)}"
    return fallback


def load_records(payload) -> list[dict]:
    """Scraper output is sometimes a bare list, sometimes wrapped."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("posts", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def normalize(rec: dict, group_name: str, source: str,
              slug: str | None = None) -> RawPost:
    text = _first(rec, *_TEXT_KEYS) or ""
    url = _first(rec, *_URL_KEYS)
    if not url and slug and rec.get("id"):
        url = f"https://www.facebook.com/groups/{slug}/posts/{rec['id']}"

    author = rec.get("author") or rec.get("user") or {}
    if isinstance(author, dict):
        author_name = _first(author, *_AUTHOR_NAME_KEYS)
        author_url = _first(author, *_AUTHOR_URL_KEYS)
    else:
        author_name, author_url = str(author), None
    author_name = author_name or _first(rec, "author_name", "username", "userName")
    author_url = clean_author_url(
        author_url or _first(rec, "author_url", "profile_url", "userUrl"))

    posted = _first(rec, *_TIME_KEYS)
    digest = hashlib.sha1(
        f"{group_name}|{author_name}|{text[:200]}".encode()).hexdigest()
    fallback = f"fbpost:{rec['id']}" if rec.get("id") else f"hash:{digest}"

    return RawPost(
        id=canonical_pid(url, fallback),
        source=source,
        url=url,
        group_name=group_name,
        author_name=author_name,
        author_url=author_url,
        posted_at=str(posted) if posted else None,
        text=text,
    )
```

- [ ] **Step 5: Write `sublease/sources/__init__.py`**

```python
from sublease.sources.base import RawPost, Source
from sublease.sources.normalize import canonical_pid, clean_author_url, normalize

__all__ = ["RawPost", "Source", "canonical_pid", "clean_author_url", "normalize"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_normalize.py -v`
Expected: 12 passed

- [ ] **Step 7: Commit**

```bash
git add sublease/sources tests/test_normalize.py
git commit -m "feat: cross-scraper post normalization with canonical Facebook ids"
```

---

## Task 6: FixtureSource and the source registry

**Files:**
- Create: `sublease/sources/fixtures.py`, `sublease/sources/registry.py`
- Modify: `sublease/sources/__init__.py`
- Test: `tests/test_sources_fixtures.py`

**Interfaces:**
- Consumes: Task 5 `RawPost`, `normalize`, `load_records`; Task 2 `SourceConfig`
- Produces: `FixtureSource(path: Path)` implementing `Source`; `sublease.sources.registry.get_source(method: str, **kw) -> Source`, `REGISTERED_METHODS: set[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sources_fixtures.py
import json
from datetime import date
from pathlib import Path
import pytest
from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.fixtures import FixtureSource
from sublease.sources.registry import REGISTERED_METHODS, get_source

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "posts.json"
CFG = SourceConfig(slug="test", name="Fixture Group", method="fixtures")


def test_fixture_source_reads_the_repo_fixtures():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=100)
    assert len(posts) == 10


def test_every_fixture_post_is_normalized():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=100)
    assert {p["id"] for p in posts} == {f"fbpost:{n}" for n in range(1, 11)}
    assert all(p["source"] == "fixtures" for p in posts)
    assert all(p["text"] for p in posts)


def test_fixture_source_uses_each_records_own_group_name():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=100)
    assert {p["group_name"] for p in posts} == {"Fixture Group"}


def test_limit_is_respected():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=3)
    assert len(posts) == 3


def test_missing_fixture_file_raises_source_error(tmp_path):
    with pytest.raises(SourceError):
        FixtureSource(tmp_path / "nope.json").fetch(CFG, date(2026, 8, 1), 10)


def test_malformed_fixture_file_raises_source_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SourceError):
        FixtureSource(bad).fetch(CFG, date(2026, 8, 1), 10)


def test_registry_knows_the_three_methods():
    assert REGISTERED_METHODS == {"fixtures", "forage", "apify"}


def test_registry_returns_a_fixture_source():
    assert isinstance(get_source("fixtures", path=FIXTURES), FixtureSource)


def test_registry_rejects_an_unknown_method():
    with pytest.raises(SourceError):
        get_source("carrier-pigeon")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources_fixtures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.sources.fixtures'`

- [ ] **Step 3: Write `sublease/sources/fixtures.py`**

```python
"""Synthetic posts, so the whole pipeline is exercisable with no Facebook."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.base import RawPost
from sublease.sources.normalize import load_records, normalize


class FixtureSource:
    name = "fixtures"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        try:
            payload = json.loads(self.path.read_text())
        except OSError as exc:
            raise SourceError(f"cannot read fixtures at {self.path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SourceError(f"fixtures at {self.path} are not valid JSON: {exc}") from exc

        records = load_records(payload)[:limit]
        return [
            normalize(rec, rec.get("group") or cfg.name, self.name, slug=cfg.slug)
            for rec in records
        ]
```

- [ ] **Step 4: Write `sublease/sources/registry.py`**

```python
"""Method name -> Source implementation."""
from __future__ import annotations

from sublease.errors import SourceError
from sublease.sources.base import Source

REGISTERED_METHODS = {"fixtures", "forage", "apify"}


def get_source(method: str, **kwargs) -> Source:
    if method == "fixtures":
        from sublease.sources.fixtures import FixtureSource
        return FixtureSource(kwargs["path"])
    if method == "forage":
        from sublease.sources.forage import ForageFacebookSource
        return ForageFacebookSource(**kwargs)
    if method == "apify":
        from sublease.sources.apify import ApifySource
        return ApifySource(**kwargs)
    raise SourceError(
        f"unknown source method {method!r}; expected one of {sorted(REGISTERED_METHODS)}")
```

- [ ] **Step 5: Update `sublease/sources/__init__.py`**

```python
from sublease.sources.base import RawPost, Source
from sublease.sources.fixtures import FixtureSource
from sublease.sources.normalize import canonical_pid, clean_author_url, normalize
from sublease.sources.registry import REGISTERED_METHODS, get_source

__all__ = [
    "RawPost", "Source", "FixtureSource", "canonical_pid", "clean_author_url",
    "normalize", "get_source", "REGISTERED_METHODS",
]
```

- [ ] **Step 6: Run tests — the two registry cases for forage/apify will fail to import**

Run: `uv run pytest tests/test_sources_fixtures.py -v`
Expected: 9 passed (`get_source` imports forage/apify lazily, so the unwritten modules are not touched by these tests)

- [ ] **Step 7: Commit**

```bash
git add sublease/sources tests/test_sources_fixtures.py
git commit -m "feat: fixture source and source registry"
```

---

## Task 7: ForageFacebook and Apify sources

**Files:**
- Create: `sublease/sources/forage.py`, `sublease/sources/apify.py`
- Test: `tests/test_sources_external.py`

**Interfaces:**
- Consumes: Task 5 `normalize`/`load_records`, Task 6 registry
- Produces: `ForageFacebookSource(binary: str = "forage", raw_dir: Path | None = None, delay: float = 3.0, runner=subprocess.run)`; `ApifySource(token: str, http=httpx.Client)`. Both implement `Source`.

Both take their subprocess/HTTP callable as a constructor argument so tests inject a double and never shell out or hit the network.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sources_external.py
import json
import subprocess
from datetime import date
from pathlib import Path
import pytest
from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.apify import ApifySource
from sublease.sources.forage import ForageFacebookSource

CFG = SourceConfig(slug="nycsublets", name="NYC Sublets", method="forage")
PAYLOAD = [{"text": "ISO a room Aug 20 - Sep 1",
            "url": "https://facebook.com/groups/nycsublets/posts/42",
            "author": {"name": "Ivan", "url": "/ivan"}, "time": "2026-08-10"}]


def fake_runner_writing(payload, returncode=0, stderr=""):
    def run(cmd, **kwargs):
        out_index = cmd.index("-o") + 1
        Path(cmd[out_index]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)
    return run


def test_forage_normalizes_scraped_posts(tmp_path):
    src = ForageFacebookSource(raw_dir=tmp_path, runner=fake_runner_writing(PAYLOAD))
    posts = src.fetch(CFG, since=date(2026, 8, 1), limit=300)
    assert [p["id"] for p in posts] == ["fbpost:42"]
    assert posts[0]["group_name"] == "NYC Sublets"
    assert posts[0]["source"] == "forage"


def test_forage_passes_days_limit_and_delay(tmp_path):
    seen = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_text("[]")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    ForageFacebookSource(raw_dir=tmp_path, delay=4.5, runner=run).fetch(
        CFG, since=date(2026, 8, 8), limit=150)
    cmd = seen["cmd"]
    assert cmd[1:3] == ["scrape", "nycsublets"]
    assert cmd[cmd.index("--days") + 1] == "3"
    assert cmd[cmd.index("--limit") + 1] == "150"
    assert cmd[cmd.index("--delay") + 1] == "4.5"
    assert "--skip-comments" in cmd and "--no-input" in cmd


def test_forage_raises_source_error_on_nonzero_exit(tmp_path):
    src = ForageFacebookSource(
        raw_dir=tmp_path, runner=fake_runner_writing([], 1, "session expired"))
    with pytest.raises(SourceError, match="session expired"):
        src.fetch(CFG, since=date(2026, 8, 1), limit=10)


def test_forage_raises_source_error_on_unreadable_output(tmp_path):
    def run(cmd, **kwargs):
        Path(cmd[cmd.index("-o") + 1]).write_text("{broken")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(SourceError):
        ForageFacebookSource(raw_dir=tmp_path, runner=run).fetch(
            CFG, since=date(2026, 8, 1), limit=10)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_apify_normalizes_and_sends_the_group_url():
    http = FakeHttp(FakeResponse(PAYLOAD))
    posts = ApifySource(token="tok", http=http).fetch(
        SourceConfig(slug="nycsublets", name="NYC Sublets", method="apify"),
        since=date(2026, 8, 1), limit=50)
    assert [p["id"] for p in posts] == ["fbpost:42"]
    url, kwargs = http.calls[0]
    assert "apify" in url
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    body = kwargs["json"]
    assert body["startUrls"][0]["url"].endswith("/groups/nycsublets")
    assert body["resultsLimit"] == 50


def test_apify_raises_source_error_on_http_failure():
    http = FakeHttp(FakeResponse({}, status=500))
    with pytest.raises(SourceError):
        ApifySource(token="tok", http=http).fetch(CFG, date(2026, 8, 1), 10)


def test_apify_requires_a_token():
    with pytest.raises(SourceError):
        ApifySource(token="", http=FakeHttp(FakeResponse([])))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources_external.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.sources.forage'`

- [ ] **Step 3: Write `sublease/sources/forage.py`**

```python
"""ForageFacebook CLI adapter — drives the user's own logged-in browser session.

Ported from reference/pipeline/scrape.py:91-117. `runner` is injectable so tests
never shell out.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from sublease.errors import SourceError
from sublease.paths import sublease_home
from sublease.profile.models import SourceConfig
from sublease.sources.base import RawPost
from sublease.sources.normalize import load_records, normalize

TIMEOUT_SECONDS = 3600


class ForageFacebookSource:
    name = "forage"

    def __init__(self, binary: str | None = None, raw_dir: Path | None = None,
                 delay: float = 3.0, runner=subprocess.run) -> None:
        # Prefer the forage installed alongside this interpreter, as the prototype did.
        self.binary = binary or str(Path(sys.executable).parent / "forage")
        self.raw_dir = Path(raw_dir) if raw_dir else sublease_home(create=True) / "raw"
        self.delay = delay
        self.runner = runner

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        outfile = self.raw_dir / f"{cfg.slug}.json"
        days = max((date.today() - since).days, 1)
        cmd = [
            self.binary, "scrape", str(cfg.slug),
            "--days", str(days),
            "--skip-comments", "--skip-reactions", "--no-input",
            "--delay", str(self.delay),
            "--limit", str(limit),
            "-f", "json", "-o", str(outfile),
        ]
        try:
            result = self.runner(cmd, capture_output=True, text=True,
                                 timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SourceError(f"could not run forage for {cfg.name}: {exc}") from exc

        if result.returncode != 0:
            raise SourceError(
                f"forage failed for {cfg.name}: {(result.stderr or '').strip()[:500]}")
        try:
            payload = json.loads(outfile.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceError(f"unreadable forage output for {cfg.name}: {exc}") from exc

        return [normalize(rec, cfg.name, self.name, slug=str(cfg.slug))
                for rec in load_records(payload)]
```

- [ ] **Step 4: Write `sublease/sources/apify.py`**

```python
"""Apify actor adapter for public groups the user has not joined.

Ported from reference/pipeline/scrape.py:119-139.
"""
from __future__ import annotations

from datetime import date

from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.base import RawPost
from sublease.sources.normalize import load_records, normalize

ACTOR = "apify~facebook-groups-scraper"
ENDPOINT = (f"https://api.apify.com/v2/acts/{ACTOR}"
            "/run-sync-get-dataset-items?timeout=280&format=json")
TIMEOUT_SECONDS = 300


class ApifySource:
    name = "apify"

    def __init__(self, token: str, http=None) -> None:
        if not token:
            raise SourceError("apify source needs APIFY_TOKEN to be set")
        self.token = token
        if http is None:
            import httpx
            http = httpx.Client(timeout=TIMEOUT_SECONDS)
        self.http = http

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        body = {
            "startUrls": [{"url": f"https://www.facebook.com/groups/{cfg.slug}"}],
            "resultsLimit": limit,
            "viewOption": "CHRONOLOGICAL",
        }
        try:
            response = self.http.post(
                ENDPOINT, json=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.token}"})
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceError(f"apify failed for {cfg.name}: {exc}") from exc

        return [normalize(rec, cfg.name, self.name, slug=str(cfg.slug))
                for rec in load_records(payload)]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_external.py -v`
Expected: 7 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: all passing (Tasks 1-7)

- [ ] **Step 7: Commit**

```bash
git add sublease/sources tests/test_sources_external.py
git commit -m "feat: ForageFacebook and Apify source adapters with injectable transports"
```

---

*(Tasks 8-21 continue in the second half of this plan — see `2026-08-11-m1-core-engine-part2.md`.)*
