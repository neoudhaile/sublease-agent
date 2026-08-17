"""What the model is asked to return.

Dates are strings here, not `date` objects: structured-output support for the
`date` format varies across providers, and Ollama enforces nothing at all. The
runner parses and validates them, so a model that emits "next Tuesday" degrades
to a null rather than an exception.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Confidence = Literal["high", "medium", "low"]
Gender = Literal["male", "female"]


class ExtractionItem(BaseModel):
    id: str
    is_seeking: bool
    start_date: str | None = None
    end_date: str | None = None
    date_text: str | None = None
    budget: str | None = None
    confidence: Confidence = "low"


class ExtractionBatch(BaseModel):
    results: list[ExtractionItem]


class EnrichmentItem(BaseModel):
    id: str
    people_in_one_room: int = 1
    wants_multiple_rooms: bool = False
    gender: Gender | None = None
    group_size: int = 1


class EnrichmentBatch(BaseModel):
    results: list[EnrichmentItem]


UnitType = Literal["room", "whole_unit"]
Bath = Literal["shared", "private"]
PriceUnit = Literal["night", "week", "month", "period"]


class OfferItem(BaseModel):
    # Rejects unknown fields so an ExtractionBatch- or EnrichmentBatch-shaped
    # payload (e.g. carrying "is_seeking" or "confidence") cannot silently
    # satisfy this schema with every real offer field defaulted to null — the
    # marker-collision hazard tests/fakes.py documents. A genuinely sparse
    # listing (only `id` known) still validates fine, since omitting an
    # optional field is not the same as sending an extra, unrecognized one.
    model_config = ConfigDict(extra="forbid")

    id: str
    price_amount: str | float | int | None = None
    price_unit: PriceUnit | None = None
    currency: str | None = None
    neighborhood: str | None = None
    unit_type: UnitType | None = None
    bedrooms: str | int | None = None
    bath: Bath | None = None
    furnished: bool | None = None
    start_date: str | None = None
    end_date: str | None = None


class OfferBatch(BaseModel):
    results: list[OfferItem]
