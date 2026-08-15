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
