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
