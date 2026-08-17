"""Select and summarize comparable offers for a place.

Pure and model-free: `neighborhood_matches` is injected as a callable
precisely so this module never imports a provider or the store. The
model-backed implementation of that callable is a later task's job; here it
is just a `(place_neighborhood: str, offer_neighborhood: str) -> bool`
contract.

Filters, in the order the design doc ranks them:
  1. Neighborhood — decided entirely by the injected callable. A comp with
     no neighborhood string at all can never be judged, so it is dropped
     without even calling the callable.
  2. Unit type — hard filter. A room is never compared against a whole unit.
  3. Bedrooms — soft. Used only to order the surviving comps, never to
     exclude one.

A comp with no `nightly_price` is dropped before any of the above — it
failed conversion upstream (see `normalize.py`) and must never reach the
median.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median as _median
from typing import Callable

from sublease.profile.models import Place

THIN_THRESHOLD = 5

NeighborhoodMatcher = Callable[[str, str], bool]


@dataclass(frozen=True)
class CompSet:
    comps: list[dict] = field(default_factory=list)
    median: float | None = None
    low: float | None = None
    high: float | None = None
    count: int = 0
    dropped: int = 0
    thin: bool = True


def _bedroom_key(offer: dict, target_bedrooms: int) -> tuple[int, int]:
    bedrooms = offer.get("bedrooms")
    if bedrooms is None:
        return (1, 0)  # unknown bedrooms sort after every known value
    return (0, abs(bedrooms - target_bedrooms))


def select_comps(offers: list[dict], place: Place,
                  neighborhood_matches: NeighborhoodMatcher) -> CompSet:
    """Filter `offers` down to comps usable for `place`, and summarize them."""
    usable: list[dict] = []
    dropped = 0

    for offer in offers:
        if offer.get("nightly_price") is None:
            dropped += 1
            continue
        neighborhood = offer.get("neighborhood")
        if not neighborhood:
            dropped += 1
            continue
        if offer.get("unit_type") != place.unit_type:
            dropped += 1
            continue
        if not neighborhood_matches(place.neighborhood, neighborhood):
            dropped += 1
            continue
        usable.append(offer)

    usable.sort(key=lambda o: _bedroom_key(o, place.bedrooms))

    count = len(usable)
    if count == 0:
        return CompSet(comps=[], median=None, low=None, high=None,
                       count=0, dropped=dropped, thin=True)

    prices = [offer["nightly_price"] for offer in usable]
    return CompSet(
        comps=usable,
        median=_median(prices),
        low=min(prices),
        high=max(prices),
        count=count,
        dropped=dropped,
        thin=count < THIN_THRESHOLD,
    )
