# Sublease Agent M1 — Part 2: LLM Providers and Extraction (Tasks 8–12)

> Continues `2026-08-11-m1-core-engine.md`. The header, Global Constraints, and File Structure in Part 1 apply to every task here.

---

## Task 8: LLM provider protocol, registry, and test double

**Files:**
- Create: `sublease/llm/__init__.py`, `sublease/llm/base.py`, `sublease/llm/registry.py`, `tests/fakes.py`
- Test: `tests/test_llm_registry.py`

**Interfaces:**
- Consumes: `sublease.errors.ProviderError`
- Produces:
  - `ProviderHealth(ok: bool, detail: str)` — frozen dataclass
  - `LLMProvider` protocol: `.name: str`, `.model: str`, `.extract_json(prompt: str, schema: type[BaseModel]) -> BaseModel`, `.health() -> ProviderHealth`
  - `sublease.llm.registry.get_provider(name: str, model: str | None = None, **kw) -> LLMProvider`, `PROVIDER_NAMES: set[str]`, `DEFAULT_PROVIDER = "anthropic"`, `DEFAULT_MODEL = "claude-haiku-4-5"`
  - `tests.fakes.FakeProvider(responses: dict[str, dict] | None = None, fail_on: set[str] | None = None)` with `.calls: list[str]`

`FakeProvider` is how every later test avoids the network. It keys canned responses by a marker string found in the prompt, and raises `ProviderError` for any post id in `fail_on` — that is how Task 12 exercises bisect recovery.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_registry.py
import pytest
from pydantic import BaseModel
from sublease.errors import ProviderError
from sublease.llm.base import ProviderHealth
from sublease.llm.registry import (
    DEFAULT_MODEL, DEFAULT_PROVIDER, PROVIDER_NAMES, get_provider,
)
from tests.fakes import FakeProvider


class Payload(BaseModel):
    value: str


def test_default_provider_and_model_are_the_documented_ones():
    assert DEFAULT_PROVIDER == "anthropic"
    assert DEFAULT_MODEL == "claude-haiku-4-5"


def test_registry_lists_four_providers():
    assert PROVIDER_NAMES == {"anthropic", "openai", "ollama", "claude-cli"}


def test_unknown_provider_raises():
    with pytest.raises(ProviderError, match="unknown provider"):
        get_provider("telepathy")


def test_provider_health_is_a_value_object():
    h = ProviderHealth(ok=True, detail="reachable")
    assert (h.ok, h.detail) == (True, "reachable")


def test_fake_provider_returns_the_canned_response_for_a_marker():
    fake = FakeProvider(responses={"MARKER": {"value": "hello"}})
    assert fake.extract_json("prompt containing MARKER", Payload).value == "hello"


def test_fake_provider_records_every_prompt():
    fake = FakeProvider(responses={"MARKER": {"value": "x"}})
    fake.extract_json("one MARKER", Payload)
    fake.extract_json("two MARKER", Payload)
    assert fake.calls == ["one MARKER", "two MARKER"]


def test_fake_provider_raises_for_configured_failures():
    fake = FakeProvider(responses={"MARKER": {"value": "x"}}, fail_on={"BOOM"})
    with pytest.raises(ProviderError):
        fake.extract_json("prompt with BOOM inside", Payload)


def test_fake_provider_raises_when_no_marker_matches():
    with pytest.raises(ProviderError, match="no canned response"):
        FakeProvider(responses={}).extract_json("unmatched", Payload)


def test_fake_provider_reports_healthy():
    assert FakeProvider().health().ok is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.llm'`

- [ ] **Step 3: Write `sublease/llm/base.py`**

```python
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
```

- [ ] **Step 4: Write `sublease/llm/registry.py`**

```python
"""Provider name -> implementation.

Imports are lazy so a user with only an Anthropic key never needs httpx to
resolve an OpenAI import, and so tests can exercise the registry without every
optional dependency present.
"""
from __future__ import annotations

from sublease.errors import ProviderError
from sublease.llm.base import LLMProvider

PROVIDER_NAMES = {"anthropic", "openai", "ollama", "claude-cli"}
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-haiku-4-5"


def get_provider(name: str, model: str | None = None, **kwargs) -> LLMProvider:
    if name == "anthropic":
        from sublease.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model or DEFAULT_MODEL, **kwargs)
    if name == "openai":
        from sublease.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model or "gpt-4o-mini", **kwargs)
    if name == "ollama":
        from sublease.llm.ollama_provider import OllamaProvider
        return OllamaProvider(model=model or "llama3.1", **kwargs)
    if name == "claude-cli":
        from sublease.llm.claude_cli_provider import ClaudeCLIProvider
        return ClaudeCLIProvider(model=model or "haiku", **kwargs)
    raise ProviderError(
        f"unknown provider {name!r}; expected one of {sorted(PROVIDER_NAMES)}")
```

- [ ] **Step 5: Write `sublease/llm/__init__.py`**

```python
from sublease.llm.base import LLMProvider, ProviderHealth
from sublease.llm.registry import (
    DEFAULT_MODEL, DEFAULT_PROVIDER, PROVIDER_NAMES, get_provider,
)

__all__ = [
    "LLMProvider", "ProviderHealth", "get_provider",
    "PROVIDER_NAMES", "DEFAULT_PROVIDER", "DEFAULT_MODEL",
]
```

- [ ] **Step 6: Write `tests/fakes.py`**

```python
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_registry.py -v`
Expected: 9 passed

- [ ] **Step 8: Commit**

```bash
git add sublease/llm tests/fakes.py tests/test_llm_registry.py
git commit -m "feat: LLM provider protocol, registry, and fake provider for tests"
```

---

## Task 9: Anthropic provider with structured outputs

**Files:**
- Create: `sublease/llm/anthropic_provider.py`
- Test: `tests/test_llm_anthropic.py`

**Interfaces:**
- Consumes: Task 8 `ProviderHealth`, `ProviderError`
- Produces: `AnthropicProvider(model: str = "claude-haiku-4-5", api_key: str | None = None, client=None, max_tokens: int = 4096)` implementing `LLMProvider`

**Why the parameters look like this.** `client` is injectable so tests never construct a real SDK client. `max_tokens=4096` is a deliberate, documented choice rather than the usual 16000 default: an extraction batch of twelve posts produces roughly a thousand tokens of structured output, so this is the "deliberately short output" case. **No `thinking` and no `output_config.effort` are passed** — `effort` errors on Haiku 4.5, and extraction is a classification task that does not benefit from thinking.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_anthropic.py
import pytest
from pydantic import BaseModel
from sublease.errors import ProviderError
from sublease.llm.anthropic_provider import AnthropicProvider


class Payload(BaseModel):
    value: str


class FakeMessages:
    def __init__(self, parsed=None, error=None):
        self.parsed, self.error = parsed, error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return type("Resp", (), {"parsed_output": self.parsed})()


class FakeClient:
    def __init__(self, parsed=None, error=None):
        self.messages = FakeMessages(parsed, error)


def test_returns_the_parsed_pydantic_object():
    client = FakeClient(parsed=Payload(value="ok"))
    got = AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)
    assert got.value == "ok"


def test_sends_the_documented_default_model():
    client = FakeClient(parsed=Payload(value="ok"))
    AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)
    assert client.messages.kwargs["model"] == "claude-haiku-4-5"


def test_passes_the_schema_as_output_format():
    client = FakeClient(parsed=Payload(value="ok"))
    AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)
    assert client.messages.kwargs["output_format"] is Payload


def test_never_sends_thinking_or_effort_which_error_on_haiku():
    client = FakeClient(parsed=Payload(value="ok"))
    AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)
    assert "thinking" not in client.messages.kwargs
    assert "output_config" not in client.messages.kwargs


def test_uses_a_bounded_max_tokens_for_batch_extraction():
    client = FakeClient(parsed=Payload(value="ok"))
    AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)
    assert client.messages.kwargs["max_tokens"] == 4096


def test_sdk_errors_become_provider_errors():
    client = FakeClient(error=RuntimeError("overloaded"))
    with pytest.raises(ProviderError, match="overloaded"):
        AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)


def test_missing_parsed_output_becomes_a_provider_error():
    client = FakeClient(parsed=None)
    with pytest.raises(ProviderError, match="no parsed output"):
        AnthropicProvider(client=client, api_key="k").extract_json("p", Payload)


def test_health_reports_ok_when_a_trivial_call_succeeds():
    client = FakeClient(parsed=Payload(value="ok"))
    assert AnthropicProvider(client=client, api_key="k").health().ok is True


def test_health_reports_the_failure_detail_without_raising():
    client = FakeClient(error=RuntimeError("bad key"))
    health = AnthropicProvider(client=client, api_key="k").health()
    assert health.ok is False and "bad key" in health.detail


def test_missing_api_key_is_reported_by_health_not_by_construction(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    health = AnthropicProvider(client=None, api_key=None).health()
    assert health.ok is False and "ANTHROPIC_API_KEY" in health.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_anthropic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.llm.anthropic_provider'`

- [ ] **Step 3: Write `sublease/llm/anthropic_provider.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_anthropic.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add sublease/llm/anthropic_provider.py tests/test_llm_anthropic.py
git commit -m "feat: Anthropic provider using structured outputs for extraction"
```

---

## Task 10: OpenAI, Ollama, and claude-cli providers

**Files:**
- Create: `sublease/llm/openai_provider.py`, `sublease/llm/ollama_provider.py`, `sublease/llm/claude_cli_provider.py`
- Test: `tests/test_llm_other_providers.py`

**Interfaces:**
- Consumes: Task 8 base types
- Produces:
  - `OpenAIProvider(model="gpt-4o-mini", api_key=None, http=None, max_tokens=4096)`
  - `OllamaProvider(model="llama3.1", base_url="http://localhost:11434", http=None)`
  - `ClaudeCLIProvider(model="haiku", binary="claude", runner=subprocess.run)`

All three lack native Pydantic-schema output, so each requests JSON mode and validates client-side with `schema.model_validate_json`. `ClaudeCLIProvider` keeps the prototype's substring extraction, since the CLI returns prose-wrapped text.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_other_providers.py
import json
import subprocess
import pytest
from pydantic import BaseModel
from sublease.errors import ProviderError
from sublease.llm.claude_cli_provider import ClaudeCLIProvider
from sublease.llm.ollama_provider import OllamaProvider
from sublease.llm.openai_provider import OpenAIProvider


class Payload(BaseModel):
    value: str


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, response):
        self.response, self.calls = response, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def openai_response(content):
    return FakeResponse({"choices": [{"message": {"content": content}}]})


def test_openai_parses_the_chat_completion_body():
    http = FakeHttp(openai_response(json.dumps({"value": "ok"})))
    got = OpenAIProvider(api_key="k", http=http).extract_json("p", Payload)
    assert got.value == "ok"


def test_openai_requests_json_object_mode():
    http = FakeHttp(openai_response(json.dumps({"value": "ok"})))
    OpenAIProvider(api_key="k", http=http).extract_json("p", Payload)
    body = http.calls[0][1]["json"]
    assert body["response_format"] == {"type": "json_object"}


def test_openai_sends_the_bearer_token():
    http = FakeHttp(openai_response(json.dumps({"value": "ok"})))
    OpenAIProvider(api_key="secret", http=http).extract_json("p", Payload)
    assert http.calls[0][1]["headers"]["Authorization"] == "Bearer secret"


def test_openai_schema_violation_is_a_provider_error():
    http = FakeHttp(openai_response(json.dumps({"wrong": "shape"})))
    with pytest.raises(ProviderError):
        OpenAIProvider(api_key="k", http=http).extract_json("p", Payload)


def test_openai_http_failure_is_a_provider_error():
    http = FakeHttp(FakeResponse({}, status=500))
    with pytest.raises(ProviderError):
        OpenAIProvider(api_key="k", http=http).extract_json("p", Payload)


def test_ollama_parses_its_response_envelope():
    http = FakeHttp(FakeResponse({"response": json.dumps({"value": "local"})}))
    assert OllamaProvider(http=http).extract_json("p", Payload).value == "local"


def test_ollama_asks_for_json_format_and_no_streaming():
    http = FakeHttp(FakeResponse({"response": json.dumps({"value": "x"})}))
    OllamaProvider(http=http).extract_json("p", Payload)
    body = http.calls[0][1]["json"]
    assert body["format"] == "json" and body["stream"] is False


def test_ollama_targets_the_configured_base_url():
    http = FakeHttp(FakeResponse({"response": json.dumps({"value": "x"})}))
    OllamaProvider(base_url="http://box:9999", http=http).extract_json("p", Payload)
    assert http.calls[0][0].startswith("http://box:9999")


def test_ollama_health_is_false_when_unreachable():
    class Boom:
        def post(self, *a, **k):
            raise OSError("connection refused")

    health = OllamaProvider(http=Boom()).health()
    assert health.ok is False and "connection refused" in health.detail


def fake_runner(stdout, returncode=0, stderr=""):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    return run


def test_claude_cli_extracts_json_from_prose_wrapped_output():
    runner = fake_runner('Sure! Here you go:\n{"value": "cli"}\nHope that helps.')
    got = ClaudeCLIProvider(runner=runner).extract_json("p", Payload)
    assert got.value == "cli"


def test_claude_cli_passes_model_and_headless_flags():
    seen = {}

    def run(cmd, **kwargs):
        seen["cmd"], seen["input"] = cmd, kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, '{"value":"x"}', "")

    ClaudeCLIProvider(model="haiku", runner=run).extract_json("PROMPT", Payload)
    assert seen["cmd"][:2] == ["claude", "-p"]
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "haiku"
    assert seen["input"] == "PROMPT"


def test_claude_cli_nonzero_exit_is_a_provider_error():
    runner = fake_runner("", returncode=1, stderr="not logged in")
    with pytest.raises(ProviderError, match="not logged in"):
        ClaudeCLIProvider(runner=runner).extract_json("p", Payload)


def test_claude_cli_output_without_json_is_a_provider_error():
    with pytest.raises(ProviderError, match="no JSON object"):
        ClaudeCLIProvider(runner=fake_runner("I cannot help with that.")).extract_json(
            "p", Payload)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_other_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.llm.openai_provider'`

- [ ] **Step 3: Write `sublease/llm/openai_provider.py`**

```python
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
        if http is None:
            import httpx
            http = httpx.Client(timeout=TIMEOUT_SECONDS)
        self.http = http

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
            response = self.http.post(
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

    def health(self) -> ProviderHealth:
        try:
            self.extract_json('Return the JSON object {"ok": true}.', _HealthProbe)
        except ProviderError as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(ok=True, detail=f"openai reachable ({self.model})")
```

- [ ] **Step 4: Write `sublease/llm/ollama_provider.py`**

```python
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
        if http is None:
            import httpx
            http = httpx.Client(timeout=TIMEOUT_SECONDS)
        self.http = http

    def extract_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        body = {"model": self.model, "prompt": prompt, "format": "json", "stream": False}
        try:
            response = self.http.post(f"{self.base_url}/api/generate", json=body)
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
        except ProviderError as exc:
            return ProviderHealth(ok=False, detail=str(exc))
        return ProviderHealth(ok=True, detail=f"ollama reachable ({self.model})")
```

- [ ] **Step 5: Write `sublease/llm/claude_cli_provider.py`**

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_other_providers.py -v`
Expected: 13 passed

- [ ] **Step 7: Commit**

```bash
git add sublease/llm tests/test_llm_other_providers.py
git commit -m "feat: OpenAI, Ollama, and claude-cli providers behind the same protocol"
```

---

## Task 11: Date resolution and prompt builders

**Files:**
- Create: `sublease/extract/__init__.py`, `sublease/extract/dates.py`, `sublease/extract/schemas.py`, `sublease/extract/prompts.py`
- Test: `tests/test_extract_dates.py`, `tests/test_extract_prompts.py`

**This task fixes defect 1 from the spec.** `reference/pipeline/extract.py:21-23` hardcodes `"Today's date is 2026-08-11."` and `"Labor Day 2026 is September 7."` Both are computed here from a reference date the caller passes in.

**Interfaces:**
- Consumes: nothing
- Produces:
  - `labor_day(year: int) -> date` (first Monday of September)
  - `memorial_day(year: int) -> date` (last Monday of May)
  - `date_hint_matches(text: str) -> bool` — the recall-oriented prefilter, ported from `extract.py:13-17`
  - `ExtractionItem`, `ExtractionBatch`, `EnrichmentItem`, `EnrichmentBatch` (Pydantic)
  - `build_extraction_prompt(posts: list[dict], today: date) -> str`
  - `build_enrichment_prompt(posts: list[dict]) -> str`

- [ ] **Step 1: Write the failing date test**

```python
# tests/test_extract_dates.py
from datetime import date
import pytest
from sublease.extract.dates import date_hint_matches, labor_day, memorial_day


@pytest.mark.parametrize("year,expected", [
    (2024, date(2024, 9, 2)),
    (2025, date(2025, 9, 1)),
    (2026, date(2026, 9, 7)),   # the value the prototype hardcoded
    (2027, date(2027, 9, 6)),
    (2028, date(2028, 9, 4)),
])
def test_labor_day_is_the_first_monday_of_september(year, expected):
    assert labor_day(year) == expected


@pytest.mark.parametrize("year,expected", [
    (2026, date(2026, 5, 25)),
    (2027, date(2027, 5, 31)),
])
def test_memorial_day_is_the_last_monday_of_may(year, expected):
    assert memorial_day(year) == expected


@pytest.mark.parametrize("text", [
    "Looking for a sublet in August",
    "ISO a room sept 1",
    "need a place through Labor Day",
    "available 8/20 - 9/1",
    "moving in ASAP",
    "need somewhere for a month",
    "sublet for two weeks",
    "move-in mid September",
    "available end of august",
    "early sept works",
])
def test_date_hint_matches_date_bearing_text(text):
    assert date_hint_matches(text) is True


@pytest.mark.parametrize("text", [
    "Does anyone know a good moving company that does small jobs? Thanks!",
    "Looking for roommate recommendations",
    "",
])
def test_date_hint_rejects_text_with_no_timeframe(text):
    assert date_hint_matches(text) is False


def test_date_hint_is_case_insensitive():
    assert date_hint_matches("LABOR DAY") is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_extract_dates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.extract'`

- [ ] **Step 3: Write `sublease/extract/dates.py`**

```python
"""Date facts the extraction prompt needs, computed rather than hardcoded.

The prototype baked "Today's date is 2026-08-11" and "Labor Day 2026 is
September 7" into its prompt (reference/pipeline/extract.py:21-23). For any
other user, or the same user a year later, every relative phrase resolved to the
wrong year. Everything here is derived from a reference date the caller supplies.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

# Recall-oriented prefilter: a post with no date-ish token cannot state a
# timeframe, so it never needs to reach a model.
# Ported from reference/pipeline/extract.py:13-17.
DATE_HINT = re.compile(
    r"(aug|sep\b|sept|september|labor\s*day|\b\d{1,2}\s*[/.-]\s*\d{1,2}\b|"
    r"week|month|asap|move.?in|mid|early|late|end of)",
    re.IGNORECASE,
)

MONDAY = 0


def labor_day(year: int) -> date:
    """First Monday of September."""
    for day in range(1, 8):
        candidate = date(year, 9, day)
        if candidate.weekday() == MONDAY:
            return candidate
    raise AssertionError("unreachable: September always contains a Monday in 1-7")


def memorial_day(year: int) -> date:
    """Last Monday of May."""
    last = calendar.monthrange(year, 5)[1]
    for day in range(last, last - 7, -1):
        candidate = date(year, 5, day)
        if candidate.weekday() == MONDAY:
            return candidate
    raise AssertionError("unreachable: May always contains a Monday in its last week")


def date_hint_matches(text: str) -> bool:
    return bool(DATE_HINT.search(text or ""))
```

- [ ] **Step 4: Run the date tests to verify they pass**

Run: `uv run pytest tests/test_extract_dates.py -v`
Expected: 21 passed

- [ ] **Step 5: Write the failing prompt test**

```python
# tests/test_extract_prompts.py
from datetime import date
import json
from sublease.extract.prompts import build_enrichment_prompt, build_extraction_prompt
from sublease.extract.schemas import ExtractionBatch, EnrichmentBatch

POSTS = [
    {"id": "fbpost:1", "text": "Looking for a sublet Aug 18 to Sep 8"},
    {"id": "fbpost:2", "text": "ISO a room through Labor Day"},
]


def test_extraction_prompt_states_the_supplied_reference_date():
    prompt = build_extraction_prompt(POSTS, today=date(2027, 3, 4))
    assert "Today's date is 2027-03-04" in prompt


def test_extraction_prompt_computes_labor_day_for_the_reference_year():
    assert "Labor Day 2027 is September 6" in build_extraction_prompt(
        POSTS, today=date(2027, 3, 4))


def test_extraction_prompt_does_not_hardcode_the_prototypes_year():
    prompt = build_extraction_prompt(POSTS, today=date(2030, 1, 1))
    assert "2026" not in prompt
    assert "Labor Day 2030 is September 2" in prompt


def test_extraction_prompt_tells_the_model_which_year_to_assume():
    assert "Assume the year 2027" in build_extraction_prompt(POSTS, date(2027, 3, 4))


def test_extraction_prompt_embeds_every_post_id_and_text():
    prompt = build_extraction_prompt(POSTS, today=date(2026, 8, 11))
    for post in POSTS:
        assert post["id"] in prompt
        assert post["text"] in prompt


def test_extraction_prompt_truncates_very_long_posts():
    long_post = [{"id": "fbpost:9", "text": "x" * 5000}]
    prompt = build_extraction_prompt(long_post, today=date(2026, 8, 11))
    assert "x" * 1500 in prompt
    assert "x" * 1501 not in prompt


def test_enrichment_prompt_forbids_guessing_gender_from_a_name():
    prompt = build_enrichment_prompt(POSTS)
    assert "NEVER guess from the person's name" in prompt


def test_enrichment_prompt_keeps_the_two_rooms_distinction():
    prompt = build_enrichment_prompt(POSTS)
    assert "TWO SEPARATE ROOMS" in prompt
    assert "wants_multiple_rooms" in prompt


def test_extraction_schema_accepts_a_well_formed_batch():
    batch = ExtractionBatch.model_validate({"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-18",
         "end_date": "2026-09-08", "date_text": "Aug 18 to Sep 8",
         "budget": "$1800", "confidence": "high"},
    ]})
    assert batch.results[0].is_seeking is True


def test_extraction_schema_allows_null_dates_for_undated_posts():
    batch = ExtractionBatch.model_validate({"results": [
        {"id": "fbpost:6", "is_seeking": False, "start_date": None,
         "end_date": None, "date_text": None, "budget": None, "confidence": "low"},
    ]})
    assert batch.results[0].start_date is None


def test_enrichment_schema_accepts_a_well_formed_batch():
    batch = EnrichmentBatch.model_validate({"results": [
        {"id": "fbpost:1", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": "female", "group_size": 1},
    ]})
    assert batch.results[0].gender == "female"


def test_enrichment_schema_allows_unknown_gender():
    batch = EnrichmentBatch.model_validate({"results": [
        {"id": "fbpost:1", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": None, "group_size": 1},
    ]})
    assert batch.results[0].gender is None
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_extract_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.extract.prompts'`

- [ ] **Step 7: Write `sublease/extract/schemas.py`**

```python
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
```

- [ ] **Step 8: Write `sublease/extract/prompts.py`**

```python
"""Prompt construction.

Both prompts are ported from the prototype, with one change: every date fact is
computed from the reference date the caller passes rather than written as a
literal.
"""
from __future__ import annotations

import json
from datetime import date

from sublease.extract.dates import labor_day

EXTRACTION_TRUNCATE = 1500
ENRICHMENT_TRUNCATE = 1200


def build_extraction_prompt(posts: list[dict], today: date) -> str:
    """Pass 1: is this person seeking, and for which dates?"""
    holiday = labor_day(today.year)
    header = f"""\
You extract structured data from Facebook group posts about housing.
Today's date is {today.isoformat()}. Assume the year {today.year} for any date
without a year. Labor Day {today.year} is {holiday.strftime('%B %-d')}.

For each post return an object with:
- "id": copied verbatim from the input
- "is_seeking": true ONLY if the author is LOOKING FOR a place to stay for
  themselves (or someone they represent). Posts OFFERING/listing a room,
  apartment, or sublet are false.
- "start_date": "YYYY-MM-DD" or null - start of the timeframe they need housing
- "end_date": "YYYY-MM-DD" or null
- "date_text": the verbatim phrase they used for dates, or null
- "budget": their stated budget as written (e.g. "$1500/mo"), or null
- "confidence": "high" | "medium" | "low" for the date interpretation

Interpret fuzzy phrases sensibly: "early August" ~ Aug 1-7, "mid-August" ~ Aug 15,
"late August" / "end of August" ~ Aug 25-31, "the month of August" = Aug 1-31,
"through Labor Day" = ending {holiday.isoformat()}. If they give only a start
("from Aug 20"), leave end_date null. If there is no timeframe at all, both null
with confidence "low".

Return one object per post, in the same order as the input.

POSTS:
"""
    payload = [{"id": p["id"], "text": (p["text"] or "")[:EXTRACTION_TRUNCATE]}
               for p in posts]
    return header + json.dumps(payload, ensure_ascii=False)


def build_enrichment_prompt(posts: list[dict]) -> str:
    """Pass 2: who would actually move in? Seekers only.

    The two-separate-rooms distinction is load-bearing: someone who needs two
    rooms is still one person per room, which is not the dealbreaker a couple
    sharing one room is.
    """
    header = """\
You read housing posts from people SEEKING a place, and extract who would
actually move in. For each post return an object with:
- "id": copied verbatim from the input
- "people_in_one_room": how many people would SHARE A SINGLE ROOM. A couple, or
  two people who explicitly want to live together in one room = 2. A solo
  searcher = 1. CRITICAL: someone looking for TWO SEPARATE ROOMS or a 2-bedroom
  for themselves + a friend is 1 PER ROOM - return 1 for them, and set
  "wants_multiple_rooms": true.
- "wants_multiple_rooms": true if they need 2+ separate rooms/bedrooms
- "group_size": total people who would move in (1 for solo, 2 for a couple or pair)
- "gender": "male" | "female" | null - ONLY when clearly stated or unambiguous
  from self-description ("I'm a 23 year old guy", "she/her", "girl looking").
  NEVER guess from the person's name. Use null when unclear.

Return one object per post, in the same order as the input.

POSTS:
"""
    payload = [{"id": p["id"], "text": (p["text"] or "")[:ENRICHMENT_TRUNCATE]}
               for p in posts]
    return header + json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 9: Write `sublease/extract/__init__.py`**

```python
from sublease.extract.dates import date_hint_matches, labor_day, memorial_day
from sublease.extract.prompts import build_enrichment_prompt, build_extraction_prompt
from sublease.extract.schemas import (
    EnrichmentBatch, EnrichmentItem, ExtractionBatch, ExtractionItem,
)

__all__ = [
    "date_hint_matches", "labor_day", "memorial_day",
    "build_extraction_prompt", "build_enrichment_prompt",
    "ExtractionItem", "ExtractionBatch", "EnrichmentItem", "EnrichmentBatch",
]
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/test_extract_dates.py tests/test_extract_prompts.py -v`
Expected: 33 passed

- [ ] **Step 11: Commit**

```bash
git add sublease/extract tests/test_extract_dates.py tests/test_extract_prompts.py
git commit -m "feat: computed date facts and prompt builders

Fixes the prototype's hardcoded reference date, which silently resolved every
relative phrase to 2026 regardless of when the tool ran."
```

---

## Task 12: Extraction and enrichment runners

**Files:**
- Create: `sublease/extract/runner.py`
- Modify: `sublease/extract/__init__.py`
- Test: `tests/test_extract_runner.py`

**Interfaces:**
- Consumes: Task 8 `LLMProvider`, Task 11 prompts/schemas/`date_hint_matches`
- Produces:
  - `run_extraction(posts: list[dict], provider, today: date, batch_size: int = 12) -> list[dict]` — rows shaped for `ExtractionRepo.save_many`
  - `run_enrichment(posts: list[dict], provider, batch_size: int = 12) -> list[dict]` — rows shaped for `EnrichmentRepo.save_many`
  - `parse_iso_date(value: str | None) -> str | None` — returns a valid `YYYY-MM-DD` string or `None`

Behavior ported from `extract.py:66-105` and `enrich.py:55-83`: posts with no date token skip the model entirely; a failing batch bisects to isolate the offender; a single failing post is recorded with its error rather than crashing the run.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract_runner.py
from datetime import date
from sublease.extract.runner import parse_iso_date, run_enrichment, run_extraction
from tests.fakes import FakeProvider

TODAY = date(2026, 8, 11)


def post(pid, text):
    return {"id": pid, "text": text}


def rows_by_id(rows):
    return {r["post_id"]: r for r in rows}


def test_posts_with_no_date_token_never_reach_the_model():
    provider = FakeProvider()
    rows = run_extraction([post("fbpost:6", "Anyone know a good mover? Thanks!")],
                          provider, today=TODAY)
    assert provider.calls == []
    row = rows_by_id(rows)["fbpost:6"]
    assert row["is_seeking"] is False
    assert row["error"] is None


def test_dated_posts_are_extracted_and_shaped_for_the_repository():
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-18",
         "end_date": "2026-09-08", "date_text": "Aug 18 to Sep 8",
         "budget": "$1800", "confidence": "high"},
    ]}})
    rows = run_extraction([post("fbpost:1", "sublet Aug 18 to Sep 8")],
                          provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    assert row["is_seeking"] is True
    assert row["start_date"] == "2026-08-18"
    assert row["model"] == "fake-model"


def test_batches_are_capped_at_the_batch_size():
    posts = [post(f"fbpost:{n}", "sublet in august") for n in range(1, 6)]
    provider = FakeProvider(responses={"POSTS": {"results": [
        {"id": p["id"], "is_seeking": True} for p in posts[:2]]}})
    run_extraction(posts[:2], provider, today=TODAY, batch_size=2)
    assert len(provider.calls) == 1


def test_a_failing_batch_bisects_down_to_the_offending_post():
    good = post("fbpost:1", "sublet in august")
    bad = post("fbpost:2", "sublet in august POISON")
    provider = FakeProvider(
        responses={"fbpost:1": {"results": [{"id": "fbpost:1", "is_seeking": True}]}},
        fail_on={"POISON"},
    )
    rows = rows_by_id(run_extraction([good, bad], provider, today=TODAY, batch_size=2))
    assert rows["fbpost:1"]["is_seeking"] is True
    assert rows["fbpost:2"]["is_seeking"] is False
    assert "fake failure" in rows["fbpost:2"]["error"]


def test_every_post_gets_exactly_one_row_even_when_some_fail():
    posts = [post("fbpost:1", "august"), post("fbpost:2", "august POISON"),
             post("fbpost:3", "no timeframe here")]
    provider = FakeProvider(
        responses={"fbpost:1": {"results": [{"id": "fbpost:1", "is_seeking": True}]}},
        fail_on={"POISON"})
    rows = run_extraction(posts, provider, today=TODAY, batch_size=1)
    assert sorted(r["post_id"] for r in rows) == ["fbpost:1", "fbpost:2", "fbpost:3"]


def test_a_short_model_response_is_treated_as_a_batch_failure():
    posts = [post("fbpost:1", "august"), post("fbpost:2", "august")]
    provider = FakeProvider(responses={"POSTS": {"results": [
        {"id": "fbpost:1", "is_seeking": True}]}})  # only one result for two posts
    rows = rows_by_id(run_extraction(posts, provider, today=TODAY, batch_size=2))
    assert all(r["error"] is not None for r in rows.values())


def test_unparseable_dates_become_null_rather_than_raising():
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "next Tuesday"}]}})
    rows = rows_by_id(run_extraction([post("fbpost:1", "august")], provider, TODAY))
    assert rows["fbpost:1"]["start_date"] is None


def test_parse_iso_date_accepts_valid_and_rejects_junk():
    assert parse_iso_date("2026-08-18") == "2026-08-18"
    assert parse_iso_date("2026-08-18T00:00:00") == "2026-08-18"
    assert parse_iso_date("soon") is None
    assert parse_iso_date(None) is None


def test_enrichment_shapes_rows_for_the_repository():
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "people_in_one_room": 2, "wants_multiple_rooms": False,
         "gender": "male", "group_size": 2}]}})
    rows = rows_by_id(run_enrichment([post("fbpost:1", "me and my partner")], provider))
    assert rows["fbpost:1"]["people_in_one_room"] == 2
    assert rows["fbpost:1"]["gender"] == "male"


def test_enrichment_failure_falls_back_to_a_safe_solo_default():
    provider = FakeProvider(fail_on={"POISON"})
    rows = rows_by_id(run_enrichment([post("fbpost:2", "POISON")], provider))
    assert rows["fbpost:2"]["people_in_one_room"] == 1
    assert rows["fbpost:2"]["gender"] is None


def test_enrichment_of_an_empty_list_does_nothing():
    provider = FakeProvider()
    assert run_enrichment([], provider) == []
    assert provider.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extract_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sublease.extract.runner'`

- [ ] **Step 3: Write `sublease/extract/runner.py`**

```python
"""Batched extraction with bisect recovery.

Two behaviours are ported deliberately from the prototype:

  * Posts with no date-like token skip the model entirely and are recorded as
    non-seeking (reference/pipeline/extract.py:88-94). On the prototype's live
    corpus this removed roughly a third of all posts before any spend.
  * A failing batch is split in half and retried until the offending post is
    alone, which is then recorded with its error rather than aborting the run
    (extract.py:66-75). Structured outputs removed *parsing* failures; this
    still handles refusals, timeouts, and oversized requests.
"""
from __future__ import annotations

from datetime import date

from sublease.errors import ProviderError
from sublease.extract.dates import date_hint_matches
from sublease.extract.prompts import build_enrichment_prompt, build_extraction_prompt
from sublease.extract.schemas import EnrichmentBatch, ExtractionBatch

DEFAULT_BATCH = 12


def parse_iso_date(value: str | None) -> str | None:
    """Return a canonical YYYY-MM-DD string, or None if it is not a real date."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _skipped_extraction(post: dict) -> dict:
    return {"post_id": post["id"], "is_seeking": False, "start_date": None,
            "end_date": None, "date_text": None, "budget": None,
            "confidence": "low", "model": None, "error": None}


def _failed_extraction(post: dict, model: str, reason: str) -> dict:
    return {"post_id": post["id"], "is_seeking": False, "start_date": None,
            "end_date": None, "date_text": None, "budget": None,
            "confidence": "low", "model": model, "error": reason[:300]}


def _extract_batch(posts: list[dict], provider, today: date) -> list[dict]:
    try:
        prompt = build_extraction_prompt(posts, today=today)
        batch = provider.extract_json(prompt, ExtractionBatch)
        if len(batch.results) != len(posts):
            raise ProviderError(
                f"expected {len(posts)} results, got {len(batch.results)}")
    except Exception as exc:
        if len(posts) == 1:
            return [_failed_extraction(posts[0], provider.model, str(exc))]
        mid = len(posts) // 2
        return (_extract_batch(posts[:mid], provider, today)
                + _extract_batch(posts[mid:], provider, today))

    return [
        {"post_id": item.id, "is_seeking": item.is_seeking,
         "start_date": parse_iso_date(item.start_date),
         "end_date": parse_iso_date(item.end_date),
         "date_text": item.date_text, "budget": item.budget,
         "confidence": item.confidence, "model": provider.model, "error": None}
        for item in batch.results
    ]


def run_extraction(posts: list[dict], provider, today: date,
                   batch_size: int = DEFAULT_BATCH) -> list[dict]:
    rows = [_skipped_extraction(p) for p in posts if not date_hint_matches(p["text"])]
    todo = [p for p in posts if date_hint_matches(p["text"])]
    for start in range(0, len(todo), batch_size):
        rows.extend(_extract_batch(todo[start:start + batch_size], provider, today))
    return rows


def _failed_enrichment(post: dict, model: str) -> dict:
    """A solo occupant with unstated gender — the assumption that excludes nobody."""
    return {"post_id": post["id"], "people_in_one_room": 1,
            "wants_multiple_rooms": False, "gender": None, "group_size": 1,
            "model": model}


def _enrich_batch(posts: list[dict], provider) -> list[dict]:
    try:
        batch = provider.extract_json(build_enrichment_prompt(posts), EnrichmentBatch)
        if len(batch.results) != len(posts):
            raise ProviderError(
                f"expected {len(posts)} results, got {len(batch.results)}")
    except Exception:
        if len(posts) == 1:
            return [_failed_enrichment(posts[0], provider.model)]
        mid = len(posts) // 2
        return _enrich_batch(posts[:mid], provider) + _enrich_batch(posts[mid:], provider)

    return [
        {"post_id": item.id, "people_in_one_room": item.people_in_one_room,
         "wants_multiple_rooms": item.wants_multiple_rooms, "gender": item.gender,
         "group_size": item.group_size, "model": provider.model}
        for item in batch.results
    ]


def run_enrichment(posts: list[dict], provider,
                   batch_size: int = DEFAULT_BATCH) -> list[dict]:
    rows: list[dict] = []
    for start in range(0, len(posts), batch_size):
        rows.extend(_enrich_batch(posts[start:start + batch_size], provider))
    return rows
```

- [ ] **Step 4: Update `sublease/extract/__init__.py`**

Append to the existing imports and `__all__`:

```python
from sublease.extract.runner import parse_iso_date, run_enrichment, run_extraction
```

and add `"run_extraction"`, `"run_enrichment"`, `"parse_iso_date"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_extract_runner.py -v`
Expected: 11 passed

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: all passing (Tasks 1-12)

- [ ] **Step 7: Commit**

```bash
git add sublease/extract tests/test_extract_runner.py
git commit -m "feat: batched extraction and enrichment with bisect recovery"
```

---

*(Tasks 13–17, the pure matching layer, continue in `2026-08-11-m1-core-engine-part3.md`.)*
