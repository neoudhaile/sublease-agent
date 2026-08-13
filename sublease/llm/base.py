"""What every model provider must offer.

Deliberately narrow: this package asks models for exactly one thing — a JSON
object matching a Pydantic schema. Keeping the surface at one method is what
makes four providers interchangeable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ProviderHealth:
    ok: bool
    detail: str


class LLMProvider(Protocol):
    name: str
    model: str

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """Return an instance of `schema`. Raises ProviderError on any failure."""
        ...

    def health(self) -> ProviderHealth:
        """Cheap reachability check for `sublease doctor`. Never raises."""
        ...
