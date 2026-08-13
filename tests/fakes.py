"""Test doubles. No test in this suite may reach the network."""
from __future__ import annotations

from pydantic import BaseModel

from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth


class FakeProvider:
    """Returns canned JSON keyed by a marker substring found in the prompt.

    `fail_on` holds marker strings that should raise instead — that is how the
    extraction runner's bisect recovery gets exercised without a real model.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self, responses: dict[str, dict] | None = None,
                 fail_on: set[str] | None = None) -> None:
        self.responses = responses or {}
        self.fail_on = fail_on or set()
        self.calls: list[str] = []

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        self.calls.append(prompt)
        for marker in self.fail_on:
            if marker in prompt:
                raise ProviderError(f"fake failure triggered by {marker!r}")
        for marker, payload in self.responses.items():
            if marker in prompt:
                return schema.model_validate(payload)
        raise ProviderError("no canned response matched this prompt")

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="fake provider")
