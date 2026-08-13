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
