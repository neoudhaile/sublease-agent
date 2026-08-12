# Sublease Agent M1 — Part 3: The Matching Layer (Tasks 13–16)

> Continues `2026-08-11-m1-core-engine-part2.md`. The header, Global Constraints, and File Structure in Part 1 apply to every task here.

Every module in this part is **pure** — no database, no network, no clock reads. Callers pass dates in. This is where the product's rules live, and it is the layer worth the most test effort.

---

## Task 13: Window overlap classification

**Files:**
- Create: `sublease/match/__init__.py`, `sublease/match/types.py`, `sublease/match/window.py`
- Test: `tests/test_match_window.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Fit = Literal["full-window", "inside", "wants-more", "overlap"]`
  - `CandidateFacts` dataclass: `days_covered: int`, `people_in_one_room: int | None`, `wants_multiple_rooms: bool`, `gender: str | None`
  - `Candidate` dataclass — the full row (fields listed in the code below)
  - `CoveragePlan` dataclass: `window_days: int`, `singles: list[Candidate]`, `combination: list[Candidate]`, `combination_days: int`
  - `classify(start: date | None, end: date | None, w_start: date, w_end: date) -> tuple[Fit | None, int]`

Ported from `reference/pipeline/filter_rank.py:72-91`. An open start means "flexible from the window start"; an open end means "could run to the window end" — both are treated as the seeker being available, not as a missing value that disqualifies them.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match_window.py
from datetime import date
import pytest
from sublease.match.window import classify

W_START, W_END = date(2026, 8, 18), date(2026, 9, 8)   # 22 days inclusive


def c(start, end):
    return classify(start, end, W_START, W_END)


def test_exact_match_is_full_window():
    assert c(date(2026, 8, 18), date(2026, 9, 8)) == ("full-window", 22)


def test_range_strictly_inside_the_window_is_inside():
    fit, days = c(date(2026, 8, 20), date(2026, 9, 1))
    assert (fit, days) == ("inside", 13)


def test_range_spanning_beyond_both_ends_is_wants_more():
    fit, days = c(date(2026, 8, 1), date(2026, 9, 30))
    assert (fit, days) == ("wants-more", 22)


def test_range_starting_before_and_ending_inside_is_overlap():
    fit, days = c(date(2026, 8, 1), date(2026, 9, 1))
    assert (fit, days) == ("overlap", 15)


def test_range_starting_inside_and_ending_after_is_overlap():
    fit, days = c(date(2026, 8, 25), date(2026, 10, 1))
    assert (fit, days) == ("overlap", 15)


def test_range_entirely_after_the_window_does_not_match():
    assert c(date(2026, 9, 15), date(2026, 10, 30)) == (None, 0)


def test_range_entirely_before_the_window_does_not_match():
    assert c(date(2026, 6, 1), date(2026, 7, 1)) == (None, 0)


def test_open_end_runs_to_the_window_end():
    fit, days = c(date(2026, 8, 22), None)
    assert (fit, days) == ("inside", 18)


def test_open_start_runs_from_the_window_start():
    fit, days = c(None, date(2026, 9, 1))
    assert (fit, days) == ("inside", 15)


def test_both_dates_open_does_not_match():
    assert c(None, None) == (None, 0)


def test_reversed_dates_are_swapped_rather_than_rejected():
    assert c(date(2026, 9, 8), date(2026, 8, 18)) == ("full-window", 22)


def test_single_day_overlap_at_the_window_start_counts():
    fit, days = c(date(2026, 8, 1), date(2026, 8, 18))
    assert (fit, days) == ("overlap", 1)


def test_single_day_overlap_at_the_window_end_counts():
    fit, days = c(date(2026, 9, 8), date(2026, 10, 1))
    assert (fit, days) == ("overlap", 1)


def test_one_day_before_the_window_does_not_match():
    assert c(date(2026, 8, 1), date(2026, 8, 17)) == (None, 0)


@pytest.mark.parametrize("start,end", [
    (date(2026, 8, 18), date(2026, 9, 8)),
    (date(2026, 8, 20), date(2026, 9, 1)),
])
def test_days_covered_never_exceeds_the_window_length(start, end):
    assert c(start, end)[1] <= 22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_match_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.match'`

- [ ] **Step 3: Write `sublease/match/types.py`**

```python
"""Value objects passed between the matching functions.

Plain dataclasses rather than Pydantic: nothing here crosses a trust boundary,
and these are constructed in tight loops.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Fit = Literal["full-window", "inside", "wants-more", "overlap"]

FIT_ORDER: dict[str, int] = {
    "full-window": 0, "inside": 1, "wants-more": 2, "overlap": 3,
}
TIER_ORDER: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3}


@dataclass(frozen=True)
class CandidateFacts:
    """The inputs tiering needs, and nothing else."""

    days_covered: int
    people_in_one_room: int | None = 1
    wants_multiple_rooms: bool = False
    gender: str | None = None


@dataclass
class Candidate:
    post_id: str
    person_key: str
    name: str | None
    fit: Fit
    days_covered: int
    wants_start: date | None
    wants_end: date | None
    profile_url: str | None = None
    post_url: str | None = None
    group_name: str | None = None
    post_date: str | None = None
    budget: str | None = None
    confidence: str | None = None
    date_text: str | None = None
    people_in_one_room: int | None = 1
    wants_multiple_rooms: bool = False
    gender: str | None = None
    occupants: int = 1
    post_text: str = ""
    also_posted_in: list[str] = field(default_factory=list)
    tier: str | None = None
    tier_reason: str | None = None
    draft: str | None = None

    def facts(self) -> CandidateFacts:
        return CandidateFacts(
            days_covered=self.days_covered,
            people_in_one_room=self.people_in_one_room,
            wants_multiple_rooms=self.wants_multiple_rooms,
            gender=self.gender,
        )


@dataclass(frozen=True)
class CoveragePlan:
    window_days: int
    singles: list[Candidate]
    combination: list[Candidate]
    combination_days: int
```

- [ ] **Step 4: Write `sublease/match/window.py`**

```python
"""Does this seeker's requested range overlap the user's window, and by how much?

Ported from reference/pipeline/filter_rank.py:72-91.

Open dates are treated as availability, not as missing data. Someone who says
"from Aug 22, end flexible" is available through the end of the window, and a
tool that discarded them for an absent end date would drop good candidates.
"""
from __future__ import annotations

from datetime import date

from sublease.match.types import Fit


def classify(start: date | None, end: date | None,
             w_start: date, w_end: date) -> tuple[Fit | None, int]:
    """Return (fit, days_covered). (None, 0) means no overlap at all."""
    if start is None and end is None:
        return None, 0

    start = start or w_start
    end = end or w_end
    if end < start:
        start, end = end, start

    overlap_start = max(start, w_start)
    overlap_end = min(end, w_end)
    days = (overlap_end - overlap_start).days + 1
    if days <= 0:
        return None, 0

    window_days = (w_end - w_start).days + 1
    if start >= w_start and end <= w_end:
        return ("full-window" if days >= window_days else "inside"), days
    if start <= w_start and end >= w_end:
        return "wants-more", days
    return "overlap", days
```

- [ ] **Step 5: Write `sublease/match/__init__.py`**

```python
from sublease.match.types import (
    Candidate, CandidateFacts, CoveragePlan, FIT_ORDER, Fit, TIER_ORDER,
)
from sublease.match.window import classify

__all__ = [
    "Candidate", "CandidateFacts", "CoveragePlan", "Fit",
    "FIT_ORDER", "TIER_ORDER", "classify",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_match_window.py -v`
Expected: 16 passed

- [ ] **Step 7: Commit**

```bash
git add sublease/match tests/test_match_window.py
git commit -m "feat: window overlap classification"
```

---

## Task 14: Constraint-driven tiering

**Files:**
- Create: `sublease/match/tiering.py`
- Modify: `sublease/match/__init__.py`
- Test: `tests/test_match_tiering.py`

**Interfaces:**
- Consumes: Task 2 `Constraints`, Task 13 `CandidateFacts`
- Produces: `tier_for(facts: CandidateFacts, constraints: Constraints, window_days: int) -> tuple[str, str]` returning `(tier_label, reason)` where tier is `"A" | "B" | "C" | "D"`

This is the generalization of `reference/pipeline/filter_rank.py:33-60`. The prototype's constants become fields on `Constraints`, and its defaults reproduce the original behavior exactly.

The **two-separate-rooms distinction** is load-bearing and is the rule most likely to be broken by a careless refactor: someone who needs two bedrooms is still one person per room, and must not be treated as the couple-in-one-room dealbreaker.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match_tiering.py
import pytest
from sublease.match.tiering import tier_for
from sublease.match.types import CandidateFacts
from sublease.profile.models import Constraints

WINDOW = 22


def tier(days, **facts):
    constraints = facts.pop("constraints", Constraints())
    return tier_for(CandidateFacts(days_covered=days, **facts), constraints, WINDOW)


def test_full_coverage_solo_is_tier_a():
    assert tier(22)[0] == "A"


def test_coverage_at_the_tier_a_threshold_is_tier_a():
    assert tier(20)[0] == "A"          # 20/22 = 0.909


def test_coverage_between_the_thresholds_is_tier_b():
    assert tier(15)[0] == "B"          # 15/22 = 0.682


def test_coverage_below_the_tier_b_threshold_is_tier_c():
    assert tier(10)[0] == "C"          # 10/22 = 0.455


def test_two_people_in_one_room_is_the_tier_d_dealbreaker():
    label, reason = tier(22, people_in_one_room=2)
    assert label == "D"
    assert "one room" in reason


def test_the_dealbreaker_outranks_perfect_coverage():
    assert tier(22, people_in_one_room=3)[0] == "D"


def test_someone_needing_two_separate_rooms_is_not_a_dealbreaker():
    """One person per room is fine — only one of them takes this room."""
    label, reason = tier(22, people_in_one_room=1, wants_multiple_rooms=True)
    assert label == "A"
    assert "2 rooms" in reason


def test_unknown_occupancy_is_treated_as_solo():
    assert tier(22, people_in_one_room=None)[0] == "A"


def test_a_relaxed_max_people_per_room_admits_a_couple():
    relaxed = Constraints(max_people_per_room=2)
    assert tier(22, people_in_one_room=2, constraints=relaxed)[0] == "A"
    assert tier(22, people_in_one_room=3, constraints=relaxed)[0] == "D"


def test_matching_the_gender_preference_is_noted_but_does_not_promote():
    prefers_male = Constraints(gender_preference="male")
    label, reason = tier(22, gender="male", constraints=prefers_male)
    assert label == "A"
    assert "preference" in reason


def test_not_matching_the_gender_preference_costs_exactly_one_tier():
    prefers_male = Constraints(gender_preference="male")
    label, reason = tier(22, gender="female", constraints=prefers_male)
    assert label == "B"
    assert "ranked just below" in reason


def test_a_soft_preference_never_demotes_past_tier_c():
    prefers_male = Constraints(gender_preference="male")
    assert tier(10, gender="female", constraints=prefers_male)[0] == "C"


def test_a_soft_preference_never_excludes_anyone():
    prefers_male = Constraints(gender_preference="male")
    assert tier(22, gender="female", constraints=prefers_male)[0] != "D"


def test_gender_is_ignored_entirely_when_no_preference_is_set():
    for gender in ("male", "female", None):
        assert tier(22, gender=gender)[0] == "A"


def test_unstated_gender_is_never_penalised_even_with_a_preference():
    prefers_male = Constraints(gender_preference="male")
    label, reason = tier(22, gender=None, constraints=prefers_male)
    assert label == "A"
    assert "unstated" in reason


def test_custom_coverage_thresholds_are_honored():
    strict = Constraints(tier_a_coverage=0.99, tier_b_coverage=0.95)
    assert tier(22, constraints=strict)[0] == "A"
    assert tier(21, constraints=strict)[0] == "B"     # 0.954
    assert tier(20, constraints=strict)[0] == "C"     # 0.909


def test_the_reason_always_states_the_days_covered():
    assert "15/22 days" in tier(15)[1]


def test_a_zero_length_window_does_not_divide_by_zero():
    assert tier_for(CandidateFacts(days_covered=0), Constraints(), 0)[0] == "C"


def test_defaults_reproduce_the_prototypes_household_rules():
    """The original author's setup: no couples, prefers male, 0.9/0.6 thresholds."""
    original = Constraints(gender_preference="male")
    assert tier(22, gender="male", constraints=original)[0] == "A"
    assert tier(22, gender="female", constraints=original)[0] == "B"
    assert tier(22, people_in_one_room=2, constraints=original)[0] == "D"
    assert tier(14, gender="male", constraints=original)[0] == "B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_match_tiering.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.match.tiering'`

- [ ] **Step 3: Write `sublease/match/tiering.py`**

```python
"""Rank a candidate against the household's rules.

The generalization of reference/pipeline/filter_rank.py:33-60 — the prototype's
constants are now fields on Constraints, and the defaults reproduce its
behaviour exactly.

Two rules are easy to break and worth stating plainly:

  * Wanting TWO SEPARATE ROOMS is not the dealbreaker. Only one of those people
    takes this room, so they are one person per room. The dealbreaker is two
    people sharing the single room on offer.
  * A gender preference is soft. It moves a candidate down exactly one tier and
    never excludes them, and it applies only when the seeker stated their own
    gender in their post — never when it was inferred.
"""
from __future__ import annotations

from sublease.match.types import CandidateFacts
from sublease.profile.models import Constraints

TIER_LABELS = {1: "A", 2: "B", 3: "C"}
LOWEST_RANKED_TIER = 3


def tier_for(facts: CandidateFacts, constraints: Constraints,
             window_days: int) -> tuple[str, str]:
    """Return (tier, human-readable reason). A is the best match."""
    occupants = facts.people_in_one_room or 1
    if occupants > constraints.max_people_per_room:
        return "D", (
            f"{occupants} people sharing one room "
            f"(limit is {constraints.max_people_per_room}) — household dealbreaker"
        )

    coverage = facts.days_covered / window_days if window_days else 0.0
    if coverage >= constraints.tier_a_coverage:
        rank, notes = 1, [f"covers {facts.days_covered}/{window_days} days"]
    elif coverage >= constraints.tier_b_coverage:
        rank, notes = 2, [f"covers {facts.days_covered}/{window_days} days"]
    else:
        rank, notes = LOWEST_RANKED_TIER, [
            f"covers only {facts.days_covered}/{window_days} days"]

    if constraints.gender_preference:
        if facts.gender == constraints.gender_preference:
            notes.append(f"{facts.gender} (household preference)")
        elif facts.gender is None:
            notes.append("gender unstated")
        else:
            rank = min(rank + 1, LOWEST_RANKED_TIER)
            notes.append(f"{facts.gender} (fine, ranked just below)")

    if facts.wants_multiple_rooms:
        notes.append("needs 2 rooms, only one person would take yours")

    return TIER_LABELS[rank], "; ".join(notes)
```

- [ ] **Step 4: Update `sublease/match/__init__.py`**

Add to the imports and `__all__`:

```python
from sublease.match.tiering import tier_for
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_match_tiering.py -v`
Expected: 22 passed

- [ ] **Step 6: Commit**

```bash
git add sublease/match tests/test_match_tiering.py
git commit -m "feat: constraint-driven tiering replacing hardcoded household rules"
```

---

## Task 15: Person dedupe and draft rendering

**Files:**
- Create: `sublease/match/dedupe.py`, `sublease/match/drafts.py`
- Modify: `sublease/match/__init__.py`
- Test: `tests/test_match_dedupe.py`, `tests/test_match_drafts.py`

**Interfaces:**
- Consumes: Task 13 `Candidate`, Task 2 `Templates`
- Produces:
  - `person_key(name: str | None, start: date | None, end: date | None) -> str`
  - `dedupe_people(candidates: list[Candidate]) -> list[Candidate]` — keeps the newest post per person, accumulating the others into `also_posted_in`
  - `sanitize_for_messenger(text: str) -> str`
  - `format_span(start: date | None, end: date | None) -> str`
  - `build_draft(template: str, candidate: Candidate) -> str`

The same human cross-posts to six groups; without dedupe they occupy six rows (prototype lesson 7). The Messenger sanitizer exists because Facebook's composer silently rewrites `8)` into an emoji — a draft mentioning "8) bring ID" turns into nonsense.

- [ ] **Step 1: Write the failing dedupe test**

```python
# tests/test_match_dedupe.py
from datetime import date
from sublease.match.dedupe import dedupe_people, person_key
from sublease.match.types import Candidate

START, END = date(2026, 8, 18), date(2026, 9, 8)


def cand(name, post_id, post_date, group, start=START, end=END):
    return Candidate(
        post_id=post_id, person_key=person_key(name, start, end), name=name,
        fit="full-window", days_covered=22, wants_start=start, wants_end=end,
        group_name=group, post_date=post_date)


def test_person_key_is_case_and_whitespace_insensitive():
    assert person_key("  Emma Stone ", START, END) == person_key("emma stone", START, END)


def test_person_key_separates_people_with_different_dates():
    assert person_key("Emma", START, END) != person_key("Emma", START, date(2026, 9, 1))


def test_person_key_handles_a_missing_name():
    assert person_key(None, START, END).startswith("|")


def test_person_key_handles_open_dates():
    assert person_key("Emma", START, None) != person_key("Emma", START, END)


def test_one_person_across_three_groups_collapses_to_one_row():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "Group A"),
        cand("Emma", "fbpost:2", "2026-08-10", "Group B"),
        cand("Emma", "fbpost:3", "2026-08-08", "Group C"),
    ])
    assert len(rows) == 1


def test_dedupe_keeps_the_newest_post():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "Group A"),
        cand("Emma", "fbpost:2", "2026-08-10", "Group B"),
    ])
    assert rows[0].post_id == "fbpost:2"


def test_dedupe_records_the_other_sightings():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "Group A"),
        cand("Emma", "fbpost:2", "2026-08-10", "Group B"),
        cand("Emma", "fbpost:3", "2026-08-08", "Group C"),
    ])
    assert sorted(rows[0].also_posted_in) == ["Group A", "Group C"]


def test_the_same_name_with_different_dates_is_two_people():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "A"),
        cand("Emma", "fbpost:2", "2026-08-10", "B", end=date(2026, 9, 1)),
    ])
    assert len(rows) == 2


def test_different_people_are_never_merged():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "A"),
        cand("Ivan", "fbpost:2", "2026-08-10", "B"),
    ])
    assert len(rows) == 2


def test_dedupe_of_an_empty_list_is_empty():
    assert dedupe_people([]) == []


def test_posts_with_no_date_do_not_crash_the_sort():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", None, "A"),
        cand("Emma", "fbpost:2", "2026-08-10", "B"),
    ])
    assert rows[0].post_id == "fbpost:2"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_match_dedupe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.match.dedupe'`

- [ ] **Step 3: Write `sublease/match/dedupe.py`**

```python
"""Collapse many posts into one person.

The same human cross-posts to every group they can find, and reposts for reach.
Keyed on (name, requested dates) rather than on the post id, because the post id
is exactly what differs between those sightings.

Ported from reference/pipeline/filter_rank.py:169-180.
"""
from __future__ import annotations

from datetime import date

from sublease.match.types import Candidate


def person_key(name: str | None, start: date | None, end: date | None) -> str:
    who = (name or "").strip().lower()
    return f"{who}|{start.isoformat() if start else ''}|{end.isoformat() if end else ''}"


def dedupe_people(candidates: list[Candidate]) -> list[Candidate]:
    """Keep the newest post per person; fold the rest into `also_posted_in`."""
    newest_first = sorted(candidates, key=lambda c: str(c.post_date or ""), reverse=True)

    kept: dict[str, Candidate] = {}
    for candidate in newest_first:
        seen = kept.get(candidate.person_key)
        if seen is None:
            kept[candidate.person_key] = candidate
        elif candidate.group_name and candidate.group_name not in seen.also_posted_in:
            seen.also_posted_in.append(candidate.group_name)
    return list(kept.values())
```

- [ ] **Step 4: Write the failing drafts test**

```python
# tests/test_match_drafts.py
from datetime import date
import pytest
from sublease.match.drafts import build_draft, format_span, sanitize_for_messenger
from sublease.match.types import Candidate

TEMPLATE = "Hi {first_name}! Saw your post in {group} — I have a room for {their_dates}."


def cand(name="Emma Stone", start=date(2026, 8, 18), end=date(2026, 9, 8),
         group="NYC Sublets"):
    return Candidate(post_id="fbpost:1", person_key="k", name=name,
                     fit="full-window", days_covered=22, wants_start=start,
                     wants_end=end, group_name=group)


@pytest.mark.parametrize("trap,safe", [
    ("8)", "8 )"), ("8-)", "8 )"), (":)", ": )"), (":(", ": ("),
    (":P", ": P"), (":D", ": D"), (";)", "; )"), (":/", ": /"),
])
def test_every_emoticon_trap_is_defused(trap, safe):
    assert sanitize_for_messenger(f"call me at {trap} ok") == f"call me at {safe} ok"


def test_sanitizer_leaves_ordinary_text_alone():
    text = "The room is available August 18 through September 8."
    assert sanitize_for_messenger(text) == text


def test_sanitizer_handles_several_traps_in_one_message():
    assert sanitize_for_messenger("8) and :(") == "8 ) and : ("


def test_span_with_both_dates():
    assert format_span(date(2026, 8, 18), date(2026, 9, 8)) == "Aug 18 – Sep 8"


def test_span_with_only_a_start():
    assert format_span(date(2026, 8, 22), None) == "from Aug 22"


def test_span_with_only_an_end():
    assert format_span(None, date(2026, 9, 1)) == "until Sep 1"


def test_span_with_neither_date():
    assert format_span(None, None) == "your dates"


def test_draft_substitutes_the_first_name_only():
    assert "Hi Emma!" in build_draft(TEMPLATE, cand())
    assert "Stone" not in build_draft(TEMPLATE, cand())


def test_draft_substitutes_the_group_and_dates():
    draft = build_draft(TEMPLATE, cand())
    assert "in NYC Sublets" in draft
    assert "Aug 18 – Sep 8" in draft


def test_draft_falls_back_when_the_name_is_missing():
    assert build_draft(TEMPLATE, cand(name=None)).startswith("Hi there!")


def test_draft_falls_back_when_the_group_is_missing():
    assert "in the group" in build_draft(TEMPLATE, cand(group=None))


def test_draft_output_is_always_sanitized():
    template = "Hi {first_name}, unit 8) is free."
    assert "8 )" in build_draft(template, cand())


def test_a_template_with_no_placeholders_passes_through():
    assert build_draft("Room available, message me.", cand()) == \
        "Room available, message me."
```

- [ ] **Step 5: Run it to verify it fails**

Run: `uv run pytest tests/test_match_drafts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.match.drafts'`

- [ ] **Step 6: Write `sublease/match/drafts.py`**

```python
"""Render the per-candidate outreach draft.

Ported from reference/pipeline/filter_rank.py:94-123.

The sanitizer is not cosmetic. Facebook's composer rewrites certain ASCII
sequences into emoji as you type — "8)" becomes a sunglasses face — so a draft
that mentions "unit 8) is free" arrives as gibberish. The prototype also found
that the composer turns lines beginning "- " into double bullets, which is why
listing copy is written in sentences.
"""
from __future__ import annotations

from datetime import date

from sublease.match.types import Candidate

EMOTICON_TRAPS = {
    "8)": "8 )", "8-)": "8 )", ":)": ": )", ":(": ": (",
    ":P": ": P", ":D": ": D", ";)": "; )", ":/": ": /",
}


def sanitize_for_messenger(text: str) -> str:
    for trap, safe in EMOTICON_TRAPS.items():
        text = text.replace(trap, safe)
    return text


def _short(day: date) -> str:
    return f"{day.strftime('%b')} {day.day}"


def format_span(start: date | None, end: date | None) -> str:
    if start and end:
        return f"{_short(start)} – {_short(end)}"
    if start:
        return f"from {_short(start)}"
    if end:
        return f"until {_short(end)}"
    return "your dates"


def build_draft(template: str, candidate: Candidate) -> str:
    name = (candidate.name or "").strip()
    first_name = name.split()[0] if name else "there"
    text = (template
            .replace("{first_name}", first_name)
            .replace("{their_dates}", format_span(candidate.wants_start,
                                                  candidate.wants_end))
            .replace("{group}", candidate.group_name or "the group"))
    return sanitize_for_messenger(text)
```

- [ ] **Step 7: Update `sublease/match/__init__.py`**

Add to the imports and `__all__`:

```python
from sublease.match.dedupe import dedupe_people, person_key
from sublease.match.drafts import build_draft, format_span, sanitize_for_messenger
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_match_dedupe.py tests/test_match_drafts.py -v`
Expected: 11 + 20 = 31 passed

- [ ] **Step 9: Commit**

```bash
git add sublease/match tests/test_match_dedupe.py tests/test_match_drafts.py
git commit -m "feat: person-level dedupe and Messenger-safe draft rendering"
```

---

## Task 16: Coverage via interval set-cover

**Files:**
- Create: `sublease/match/coverage.py`
- Modify: `sublease/match/__init__.py`
- Test: `tests/test_match_coverage.py`

**This task fixes defects 2 and 3 from the spec.**

The prototype enumerated `combinations(partials, 2)` and built a `set` of `date` objects day by day for each pair (`reference/pipeline/filter_rank.py:229-241`). Two problems: it could only ever find **pairs**, so the three-person split that actually filled the author's window was invisible to the tool that was supposed to find it; and the day-by-day set construction is quadratic in candidates and linear in window length.

This replaces both with greedy interval set-cover up to `max_split` seekers, using interval arithmetic.

**Interfaces:**
- Consumes: Task 13 `Candidate`, `CoveragePlan`
- Produces:
  - `clip(candidate, w_start, w_end) -> tuple[date, date] | None`
  - `subtract(uncovered: list[tuple[date, date]], taken: tuple[date, date]) -> list[tuple[date, date]]`
  - `overlap_days(a, b) -> int`
  - `coverage(candidates, w_start, w_end, max_split=3, near_complete_slack=2) -> CoveragePlan`

Greedy set-cover is not guaranteed optimal, but for interval cover on a single timeline with a handful of picks it is optimal in practice and runs in a fraction of the time an exhaustive search over 3-subsets would take.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match_coverage.py
from datetime import date
from sublease.match.coverage import clip, coverage, overlap_days, subtract
from sublease.match.types import Candidate

W_START, W_END = date(2026, 8, 18), date(2026, 9, 8)


def cand(name, start, end, days=None):
    lo, hi = max(start, W_START), min(end, W_END)
    return Candidate(
        post_id=f"p:{name}", person_key=name, name=name, fit="inside",
        days_covered=days if days is not None else (hi - lo).days + 1,
        wants_start=start, wants_end=end)


def d(day):
    return date(2026, 8, day) if day <= 31 else date(2026, 9, day - 31)


def test_overlap_days_counts_inclusive_days():
    assert overlap_days((d(18), d(20)), (d(19), d(25))) == 2


def test_overlap_days_is_zero_when_disjoint():
    assert overlap_days((d(18), d(20)), (d(21), d(25))) == 0


def test_clip_trims_a_range_to_the_window():
    c = cand("x", date(2026, 8, 1), date(2026, 9, 30))
    assert clip(c, W_START, W_END) == (W_START, W_END)


def test_clip_returns_none_for_a_range_outside_the_window():
    c = cand("x", date(2026, 9, 20), date(2026, 10, 1))
    assert clip(c, W_START, W_END) is None


def test_clip_treats_open_dates_as_the_window_edges():
    c = Candidate(post_id="p", person_key="k", name="x", fit="inside",
                  days_covered=22, wants_start=None, wants_end=None)
    assert clip(c, W_START, W_END) == (W_START, W_END)


def test_subtract_removes_a_middle_slice_leaving_two_gaps():
    assert subtract([(d(18), d(28))], (d(21), d(23))) == [(d(18), d(20)), (d(24), d(28))]


def test_subtract_trims_a_leading_slice():
    assert subtract([(d(18), d(28))], (d(18), d(20))) == [(d(21), d(28))]


def test_subtract_removes_a_fully_covered_interval():
    assert subtract([(d(18), d(28))], (d(1), d(31))) == []


def test_subtract_leaves_a_disjoint_interval_alone():
    assert subtract([(d(18), d(20))], (d(25), d(28))) == [(d(18), d(20))]


def test_near_complete_singles_are_surfaced():
    plan = coverage([cand("Emma", W_START, W_END)], W_START, W_END)
    assert [c.name for c in plan.singles] == ["Emma"]


def test_a_partial_candidate_is_not_a_near_complete_single():
    plan = coverage([cand("Ivan", d(20), d(31))], W_START, W_END)
    assert plan.singles == []


def test_singles_tolerate_the_configured_slack():
    plan = coverage([cand("Almost", d(19), d(38))], W_START, W_END,
                    near_complete_slack=2)
    assert [c.name for c in plan.singles] == ["Almost"]


def test_two_complementary_partials_tile_the_whole_window():
    plan = coverage(
        [cand("Fiona", W_START, d(31)), cand("Nia", d(31), W_END)],
        W_START, W_END, max_split=3)
    assert plan.combination_days == 22
    assert sorted(c.name for c in plan.combination) == ["Fiona", "Nia"]


def test_three_partials_tile_a_window_two_cannot():
    """The case the prototype could not express — it only ever searched pairs."""
    plan = coverage([
        cand("A", W_START, d(24)),
        cand("B", d(25), d(31)),
        cand("C", date(2026, 9, 1), W_END),
    ], W_START, W_END, max_split=3)
    assert plan.combination_days == 22
    assert len(plan.combination) == 3


def test_max_split_caps_how_many_people_are_proposed():
    plan = coverage([
        cand("A", W_START, d(24)),
        cand("B", d(25), d(31)),
        cand("C", date(2026, 9, 1), W_END),
    ], W_START, W_END, max_split=2)
    assert len(plan.combination) == 2
    assert plan.combination_days < 22


def test_max_split_of_one_returns_the_single_best_candidate():
    plan = coverage([
        cand("Short", W_START, d(20)),
        cand("Long", W_START, d(31)),
    ], W_START, W_END, max_split=1)
    assert [c.name for c in plan.combination] == ["Long"]


def test_greedy_picks_the_largest_contribution_first():
    plan = coverage([
        cand("Small", W_START, d(19)),
        cand("Big", W_START, d(31)),
    ], W_START, W_END, max_split=2)
    assert plan.combination[0].name == "Big"


def test_a_candidate_adding_nothing_new_is_not_picked():
    plan = coverage([
        cand("Whole", W_START, W_END),
        cand("Subset", d(20), d(22)),
    ], W_START, W_END, max_split=3)
    assert [c.name for c in plan.combination] == ["Whole"]


def test_candidates_outside_the_window_are_ignored():
    plan = coverage([cand("Otis", date(2026, 9, 15), date(2026, 10, 30))],
                    W_START, W_END)
    assert plan.combination == []
    assert plan.combination_days == 0


def test_an_empty_candidate_list_yields_an_empty_plan():
    plan = coverage([], W_START, W_END)
    assert (plan.singles, plan.combination, plan.combination_days) == ([], [], 0)
    assert plan.window_days == 22


def test_the_plan_reports_the_window_length():
    assert coverage([], W_START, W_END).window_days == 22


def test_coverage_is_fast_on_a_large_candidate_pool():
    """The prototype's day-by-day pair search degraded badly here."""
    pool = [cand(f"c{n}", d(18 + n % 10), d(20 + n % 10)) for n in range(500)]
    plan = coverage(pool, W_START, W_END, max_split=3)
    assert len(plan.combination) <= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_match_coverage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.match.coverage'`

- [ ] **Step 3: Write `sublease/match/coverage.py`**

```python
"""Which combination of seekers covers the whole window?

Replaces reference/pipeline/filter_rank.py:229-241, which had two defects:

  * It enumerated `combinations(partials, 2)` and so could only ever propose
    *pairs*. The arrangement that actually filled the prototype author's window
    was a three-person split — the tool could not have surfaced the answer its
    own author found by hand.
  * It built a `set` of `date` objects day by day for every pair, which is
    quadratic in candidates and linear in window length.

Both are fixed here: greedy set-cover up to `max_split` seekers, over intervals
rather than day sets. Greedy is not provably optimal, but for interval cover on
one timeline with a handful of picks it matches exhaustive search in practice
while staying linear per pick.
"""
from __future__ import annotations

from datetime import date, timedelta

from sublease.match.types import Candidate, CoveragePlan

Interval = tuple[date, date]
ONE_DAY = timedelta(days=1)
DEFAULT_MAX_SPLIT = 3
DEFAULT_SLACK = 2
MAX_SINGLES_REPORTED = 10


def _days(interval: Interval) -> int:
    return (interval[1] - interval[0]).days + 1


def overlap_days(a: Interval, b: Interval) -> int:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return max((hi - lo).days + 1, 0)


def clip(candidate: Candidate, w_start: date, w_end: date) -> Interval | None:
    """The part of a candidate's availability that falls inside the window."""
    start = max(candidate.wants_start or w_start, w_start)
    end = min(candidate.wants_end or w_end, w_end)
    return (start, end) if start <= end else None


def subtract(uncovered: list[Interval], taken: Interval) -> list[Interval]:
    """Remove `taken` from each remaining gap, splitting where it lands inside."""
    remaining: list[Interval] = []
    for lo, hi in uncovered:
        if taken[1] < lo or taken[0] > hi:
            remaining.append((lo, hi))
            continue
        if lo < taken[0]:
            remaining.append((lo, taken[0] - ONE_DAY))
        if hi > taken[1]:
            remaining.append((taken[1] + ONE_DAY, hi))
    return remaining


def coverage(candidates: list[Candidate], w_start: date, w_end: date,
             max_split: int = DEFAULT_MAX_SPLIT,
             near_complete_slack: int = DEFAULT_SLACK) -> CoveragePlan:
    window_days = (w_end - w_start).days + 1

    singles = sorted(
        (c for c in candidates if c.days_covered >= window_days - near_complete_slack),
        key=lambda c: -c.days_covered,
    )[:MAX_SINGLES_REPORTED]

    spans: list[tuple[Candidate, Interval]] = []
    for candidate in candidates:
        interval = clip(candidate, w_start, w_end)
        if interval is not None:
            spans.append((candidate, interval))

    uncovered: list[Interval] = [(w_start, w_end)]
    chosen: list[Candidate] = []
    used: set[int] = set()

    while uncovered and len(chosen) < max_split:
        best_index, best_gain = None, 0
        for index, (_, interval) in enumerate(spans):
            if index in used:
                continue
            gain = sum(overlap_days(interval, gap) for gap in uncovered)
            if gain > best_gain:
                best_index, best_gain = index, gain
        if best_index is None:
            break
        used.add(best_index)
        candidate, interval = spans[best_index]
        chosen.append(candidate)
        uncovered = subtract(uncovered, interval)

    covered = window_days - sum(_days(gap) for gap in uncovered)
    return CoveragePlan(window_days=window_days, singles=singles,
                        combination=chosen, combination_days=covered)
```

- [ ] **Step 4: Update `sublease/match/__init__.py`**

Add to the imports and `__all__`:

```python
from sublease.match.coverage import clip, coverage, overlap_days, subtract
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_match_coverage.py -v`
Expected: 22 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: all passing (Tasks 1-16)

- [ ] **Step 7: Commit**

```bash
git add sublease/match tests/test_match_coverage.py
git commit -m "feat: interval set-cover replacing pairs-only coverage search

The prototype could only propose pairs, so the three-person split that actually
filled its author's window was invisible to it. Also replaces the quadratic
day-by-day set construction with interval arithmetic."
```

---

*(Tasks 17–21 — ranking, pipeline, CLI, and the end-to-end golden test — continue in `2026-08-11-m1-core-engine-part4.md`.)*
