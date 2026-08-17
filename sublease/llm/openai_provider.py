"""OpenAI chat completions in JSON mode, validated client-side.

Raw httpx rather than the OpenAI SDK: this package needs exactly one endpoint,
and a second heavyweight SDK is not worth the install cost for self-hosters.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, ValidationError

from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth

ENDPOINT = "https://api.openai.com/v1/chat/completions"
TIMEOUT_SECONDS = 120
MAX_TOKENS = 4096


class _HealthProbe(BaseModel):
    ok: bool


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None,
                 http=None, max_tokens: int = MAX_TOKENS) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._http = http

    def _get_http(self):
        if self._http is not None:
            return self._http
        import httpx
        self._http = httpx.Client(timeout=TIMEOUT_SECONDS)
        return self._http

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if not self._api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            http = self._get_http()
            response = http.post(
                ENDPOINT, json=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self._api_key}"})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError(f"openai request failed: {exc}") from exc
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            raise ProviderError(f"openai returned unusable JSON: {exc}") from exc

    def ready(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(ok=False, detail="OPENAI_API_KEY is not set")
        try:
            self._get_http()
        except Exception as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(
            ok=True,
            detail=f"openai configured ({self.model}); connectivity not verified")

    def health(self) -> ProviderHealth:
        try:
            self.extract_json('Return the JSON object {"ok": true}.', _HealthProbe)
        except Exception as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(ok=True, detail=f"openai reachable ({self.model})")
