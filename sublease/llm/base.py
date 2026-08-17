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

    def ready(self) -> ProviderHealth:
        """Cheap, offline check that this provider is configured: credentials
        are present and the client constructs. Issues no request, and costs
        nothing. Used by `sublease doctor`'s default check. Never raises.
        Does NOT verify connectivity — a provider can be `ready` and still
        fail its first real call.
        """
        ...

    def health(self) -> ProviderHealth:
        """Full reachability check: issues one real completion request. For
        the Anthropic and OpenAI providers this is a billable API call. Used
        only by `sublease doctor --probe`. Never raises.
        """
        ...
