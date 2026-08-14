"""Default provider. Uses structured outputs so the model returns a validated
object rather than text this package has to scrape for JSON.

This replaces the prototype's `text.find("[") / text.rfind("]")` substring hunt
(reference/pipeline/extract.py:57-62) with schema validation at the API layer.

Two parameters are deliberately absent from every request:
  * `thinking` — extraction is classification; it gains nothing from reasoning.
  * `output_config.effort` — errors on Haiku 4.5.
`max_tokens` is 4096 rather than the usual 16000 default because a twelve-post
batch of structured output runs to roughly a thousand tokens; this is the
deliberately-short-output case.
"""
from __future__ import annotations

import os

from pydantic import BaseModel

from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096


class _HealthProbe(BaseModel):
    ok: bool


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 client=None, max_tokens: int = MAX_TOKENS) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Export it, or choose another "
                "provider with `sublease init`.")
        import anthropic
        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        client = self._get_client()
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except Exception as exc:
            raise ProviderError(f"anthropic request failed: {exc}") from exc

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ProviderError("anthropic returned no parsed output")
        return parsed

    def health(self) -> ProviderHealth:
        try:
            self.extract_json(
                "Reply with the JSON object {\"ok\": true} and nothing else.",
                _HealthProbe)
        except ProviderError as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(ok=True, detail=f"anthropic reachable ({self.model})")
