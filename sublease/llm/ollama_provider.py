"""A local Ollama daemon. No key, no cost, nothing leaves the machine."""
from __future__ import annotations

from pydantic import BaseModel, ValidationError

from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth

TIMEOUT_SECONDS = 300


class _HealthProbe(BaseModel):
    ok: bool


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str = "llama3.1",
                 base_url: str = "http://localhost:11434", http=None) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._http = http

    def _get_http(self):
        if self._http is not None:
            return self._http
        import httpx
        self._http = httpx.Client(timeout=TIMEOUT_SECONDS)
        return self._http

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        body = {"model": self.model, "prompt": prompt, "format": "json", "stream": False}
        try:
            http = self._get_http()
            response = http.post(f"{self.base_url}/api/generate", json=body)
            response.raise_for_status()
            content = response.json()["response"]
        except Exception as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc
        try:
            return schema.model_validate_json(content)
        except ValidationError as exc:
            raise ProviderError(f"ollama returned unusable JSON: {exc}") from exc

    def health(self) -> ProviderHealth:
        try:
            self.extract_json('Return the JSON object {"ok": true}.', _HealthProbe)
        except Exception as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(ok=True, detail=f"ollama reachable ({self.model})")
