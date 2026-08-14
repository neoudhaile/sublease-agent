"""Drives an existing Claude Code install via `claude -p`.

Ported from reference/pipeline/extract.py:47-63. Free for anyone already
subscribed, and the zero-configuration path. The CLI returns prose-wrapped text
rather than a structured object, so the prototype's substring extraction is kept
here — this is the one provider that still needs it.
"""
from __future__ import annotations

import subprocess

from pydantic import BaseModel, ValidationError

from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth

TIMEOUT_SECONDS = 300


class _HealthProbe(BaseModel):
    ok: bool


def _first_json_object(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ProviderError(f"no JSON object in claude output: {text[:200]}")
    return text[start:end + 1]


class ClaudeCLIProvider:
    name = "claude-cli"

    def __init__(self, model: str = "haiku", binary: str = "claude",
                 runner=subprocess.run) -> None:
        self.model = model
        self.binary = binary
        self.runner = runner

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        cmd = [self.binary, "-p", "--model", self.model, "--output-format", "text"]
        try:
            result = self.runner(cmd, input=prompt, capture_output=True, text=True,
                                 timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError(f"could not run `{self.binary}`: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise ProviderError(
                f"undecodable output from `{self.binary}`: {exc}") from exc
        if result.returncode != 0:
            raise ProviderError(
                f"claude -p failed: {(result.stderr or '').strip()[:300]}")
        try:
            return schema.model_validate_json(_first_json_object(result.stdout))
        except ValidationError as exc:
            raise ProviderError(f"claude -p returned unusable JSON: {exc}") from exc

    def health(self) -> ProviderHealth:
        try:
            self.extract_json('Return the JSON object {"ok": true} and nothing else.',
                              _HealthProbe)
        except ProviderError as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(ok=True, detail=f"claude cli reachable ({self.model})")
