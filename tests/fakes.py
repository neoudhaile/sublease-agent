"""Test doubles. No test in this suite may reach the network."""
from __future__ import annotations

from pydantic import BaseModel, ValidationError

from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth


class FakeProvider:
    """Returns canned JSON keyed by a marker substring found in the prompt.

    `fail_on` holds marker strings that should raise instead — that is how the
    extraction runner's bisect recovery gets exercised without a real model.
    `fail_on` is checked before `responses`, so a marker present in both wins
    as a failure — later tasks rely on this to make one post inside a batch
    fail on purpose.

    Marker matching against `responses` is substring-based, so one marker can
    be a substring of another (e.g. "fbpost:1" inside "fbpost:10"). The
    LONGEST matching marker wins, which resolves that case correctly
    regardless of dict insertion order. If two DIFFERENT markers of equal
    length both match the same prompt, that is genuine ambiguity in the test
    fixture and raises rather than silently guessing.
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

        matches = [marker for marker in self.responses if marker in prompt]
        if not matches:
            raise ProviderError("no canned response matched this prompt")

        longest = max(len(marker) for marker in matches)
        longest_matches = [marker for marker in matches if len(marker) == longest]
        if len(longest_matches) > 1:
            raise ProviderError(
                "ambiguous canned response: prompt matches multiple markers "
                f"of equal length: {sorted(longest_matches)!r}"
            )
        marker = longest_matches[0]

        try:
            return schema.model_validate(self.responses[marker])
        except ValidationError as exc:
            raise ProviderError(
                f"canned response for marker {marker!r} does not match "
                f"schema {schema.__name__} — this is a malformed CANNED "
                f"payload in the test fixture, not a production failure: {exc}"
            ) from exc

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True, detail="fake provider")
