"""Decide whether a place gets a comps-based price or a labelled estimate.

Two modes, chosen by what data exists — never by user preference:

  * **Comps mode** — usable offers already exist in the database (from any
    profile; offers are global, like `extraction` and `enrichment`). Real
    listings are matched to the user's place and summarized.
  * **Estimate mode** — no usable offers exist yet, which is always true the
    first time `init` runs, since nothing has been scraped. One model call
    returns a per-night range grounded in the model's own knowledge, and the
    result is tagged so every caller can label it plainly as a guess.

This module is also the one production caller of `run_offer_extraction` +
`OfferRepo.save_many` — pass 3 has no other wiring into the codebase. It
extracts offers for any non-seeker post that doesn't have one yet, then reads
back whatever is usable. That keeps `sublease price` self-sufficient: a user
can run it any time after `sublease run` without a separate command syncing
the offer table first.

Every model call here can fail (`ProviderError`) if the provider is
unreachable — that is deliberately NOT swallowed here. Callers (`sublease
price`, the optional `init` step) decide what "the model is unavailable"
should look like for their flow; this module only computes.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel

from sublease.extract.runner import run_offer_extraction
from sublease.pricing.comps import CompSet, select_comps
from sublease.profile.models import Place, Window
from sublease.store.repositories import ExtractionRepo, OfferRepo, PostRepo

Mode = Literal["comps", "estimate"]
Relation = Literal["same", "adjacent", "different"]


class NeighborhoodItem(BaseModel):
    neighborhood: str
    relation: Relation


class NeighborhoodBatch(BaseModel):
    results: list[NeighborhoodItem]


class EstimateResult(BaseModel):
    low: float
    high: float
    note: str | None = None


@dataclass(frozen=True)
class PricingResult:
    mode: Mode
    place: Place
    nights: int
    comp_set: CompSet | None = None
    # Comp-neighborhood string (as written) -> "same" | "adjacent" | "different",
    # from the one model call that classified them. Empty in estimate mode.
    neighborhood_relations: dict[str, str] = field(default_factory=dict)
    estimate_low: float | None = None
    estimate_high: float | None = None
    estimate_note: str | None = None


def _sync_offer_extraction(conn: sqlite3.Connection, provider, today: date) -> None:
    """Run pass 3 over any non-seeker post that doesn't have an offer row yet.

    Write-once and idempotent, same rule as `extraction`/`enrichment`: a post
    that already has an offer row (extracted, prefiltered, or failed) is
    never re-sent, so repeated `sublease price` calls cost nothing once a
    post has been seen.
    """
    non_seeker_ids = ExtractionRepo(conn).non_seeker_ids()
    pending_ids = sorted(set(non_seeker_ids) - OfferRepo(conn).done_ids())
    if not pending_ids:
        return
    posts = list(PostRepo(conn).get_many(pending_ids).values())
    rows = run_offer_extraction(posts, provider, today=today)
    OfferRepo(conn).save_many(rows)


def _neighborhood_prompt(place: Place, neighborhoods: list[str]) -> str:
    header = f"""\
You match neighborhood names for a sublet pricing tool. The user's place is
in "{place.neighborhood}". For each of the following neighborhood strings,
taken verbatim from other listings, decide how it relates to the user's
neighborhood:
- "same": refers to the same area, including abbreviations, colloquial
  names, and alternate spellings the user's own market might use (e.g. "EV"
  or "the East Village" both mean East Village).
- "adjacent": a different but nearby/bordering area (e.g. Alphabet City is
  adjacent to the East Village) — usable as a comp, but should be labelled
  as adjacent rather than presented as the same place.
- "different": a genuinely different, non-adjacent area, or too vague or
  generic to judge (e.g. just "NYC" or "Brooklyn").

Return one object per input string, in the same order, with:
- "neighborhood": copied verbatim from the input
- "relation": "same" | "adjacent" | "different"

NEIGHBORHOODS:
"""
    return header + json.dumps(neighborhoods, ensure_ascii=False)


def _classify_neighborhoods(place: Place, neighborhoods: list[str],
                            provider) -> dict[str, str]:
    """One model call: which comp-neighborhood strings mean the same place as
    the user's, or an adjacent one? Deliberately no alias table — the model
    already knows "EV" is the East Village and that Alphabet City is next
    door, and a hardcoded list would only rot as neighborhoods and slang do.
    """
    if not neighborhoods:
        return {}
    batch = provider.extract_json(
        _neighborhood_prompt(place, neighborhoods), NeighborhoodBatch)
    return {item.neighborhood: item.relation for item in batch.results}


def _estimate_prompt(place: Place, nights: int) -> str:
    return f"""\
You estimate typical short-term room/sublet pricing from your own general
knowledge. No comparable local listings are available yet — the user is
setting up a brand-new listing and nothing has been scraped — so this is
your best estimate, NOT a real comparable listing. Say so plainly by keeping
the range honest about your uncertainty rather than falsely precise.

Place details:
- Neighborhood: {place.neighborhood}
- Unit type: {place.unit_type} ("room" = one room in a shared apartment,
  "whole_unit" = the entire apartment)
- Bedrooms: {place.bedrooms}
- Bath: {place.bath}
- Furnished: {place.furnished}
- Length of stay: {nights} nights

Return:
- "low": a conservative per-night USD estimate
- "high": a generous per-night USD estimate
- "note": an optional one-sentence caveat about the estimate's uncertainty
  (e.g. seasonal swings, how well-known the neighborhood's pricing is to
  you), or null if you have nothing worth adding
"""


def _estimate(place: Place, nights: int, provider) -> tuple[float, float, str | None]:
    result = provider.extract_json(_estimate_prompt(place, nights), EstimateResult)
    return result.low, result.high, result.note


def price_place(conn: sqlite3.Connection, place: Place, window: Window,
                provider, today: date) -> PricingResult:
    """Given a connection, a place, a window, and a working provider, return
    either real comps or a labelled estimate. Raises `ProviderError` if a
    model call this needs fails — the caller decides how "unavailable"
    should look for its own flow (see module docstring)."""
    _sync_offer_extraction(conn, provider, today)
    nights = window.days

    usable = OfferRepo(conn).usable()
    if usable:
        distinct = sorted({o["neighborhood"] for o in usable if o.get("neighborhood")})
        relations = _classify_neighborhoods(place, distinct, provider)

        def matches(place_neighborhood: str, offer_neighborhood: str) -> bool:
            return relations.get(offer_neighborhood) in ("same", "adjacent")

        comp_set = select_comps(usable, place, matches)
        return PricingResult(mode="comps", place=place, nights=nights,
                             comp_set=comp_set, neighborhood_relations=relations)

    low, high, note = _estimate(place, nights, provider)
    return PricingResult(mode="estimate", place=place, nights=nights,
                         estimate_low=low, estimate_high=high, estimate_note=note)
