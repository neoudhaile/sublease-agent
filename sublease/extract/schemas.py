"""What the model is asked to return.

Dates are strings here, not `date` objects: structured-output support for the
`date` format varies across providers, and Ollama enforces nothing at all. The
runner parses and validates them, so a model that emits "next Tuesday" degrades
to a null rather than an exception.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
