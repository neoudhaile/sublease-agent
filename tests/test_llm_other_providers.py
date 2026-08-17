import json
import subprocess
import pytest
from pydantic import BaseModel
from sublease.errors import ProviderError
from sublease.llm.claude_cli_provider import ClaudeCLIProvider, TIMEOUT_SECONDS
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


def test_openai_wraps_http_construction_error_as_provider_error(monkeypatch):
    """Constructing the default httpx.Client is deferred into extract_json's
    guarded path, so a construction failure (e.g. a bad proxy env var) is
    reported as ProviderError rather than escaping raw."""
    def boom(*args, **kwargs):
        raise RuntimeError("bad proxy config")

    monkeypatch.setattr("httpx.Client", boom)
    provider = OpenAIProvider(api_key="k", http=None)
    with pytest.raises(ProviderError, match="bad proxy config"):
        provider.extract_json("p", Payload)


def test_openai_health_handles_http_construction_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bad proxy config")

    monkeypatch.setattr("httpx.Client", boom)
    provider = OpenAIProvider(api_key="k", http=None)
    health = provider.health()
    assert health.ok is False and "bad proxy config" in health.detail


def test_ollama_wraps_http_construction_error_as_provider_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bad proxy config")

    monkeypatch.setattr("httpx.Client", boom)
    provider = OllamaProvider(http=None)
    with pytest.raises(ProviderError, match="bad proxy config"):
        provider.extract_json("p", Payload)


def test_ollama_health_handles_http_construction_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("bad proxy config")

    monkeypatch.setattr("httpx.Client", boom)
    provider = OllamaProvider(http=None)
    health = provider.health()
    assert health.ok is False and "bad proxy config" in health.detail


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


def test_claude_cli_unicode_decode_error_is_a_provider_error():
    """subprocess.run(..., text=True) raises UnicodeDecodeError when output
    is not decodable in the ambient locale. This must surface as ProviderError."""
    def boom_on_decode(cmd, **kwargs):
        # Simulate what subprocess.run does when text=True and output can't decode
        raise UnicodeDecodeError('utf-8', b'\xff\xfe', 0, 2, 'invalid start byte')

    with pytest.raises(ProviderError, match="undecodable"):
        ClaudeCLIProvider(runner=boom_on_decode).extract_json("p", Payload)


def test_claude_cli_timeout_is_a_provider_error():
    """subprocess.run raises TimeoutExpired when it times out."""
    def timeout_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, TIMEOUT_SECONDS)

    with pytest.raises(ProviderError, match="timed out"):
        ClaudeCLIProvider(runner=timeout_runner).extract_json("p", Payload)


def test_claude_cli_health_succeeds_on_good_probe():
    """health() should return ok=True when the probe succeeds."""
    runner = fake_runner('{"ok": true}')
    health = ClaudeCLIProvider(runner=runner).health()
    assert health.ok is True


def test_claude_cli_health_fails_gracefully_on_unicode_error():
    """health() should return ok=False and not raise when extract_json fails."""
    def boom_on_decode(cmd, **kwargs):
        raise UnicodeDecodeError('utf-8', b'\xff\xfe', 0, 2, 'invalid start byte')

    health = ClaudeCLIProvider(runner=boom_on_decode).health()
    assert health.ok is False
    assert "undecodable" in health.detail


def test_claude_cli_health_fails_gracefully_on_timeout():
    """health() should return ok=False and not raise when extract_json times out."""
    def timeout_runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, TIMEOUT_SECONDS)

    health = ClaudeCLIProvider(runner=timeout_runner).health()
    assert health.ok is False


# --- Fix wave 2026-08-15 -----------------------------------------------------
# Finding 3: each provider's `ready()` must confirm it's configured without
# issuing the real (billable, for openai/anthropic) request `health()` makes.

def test_openai_ready_is_ok_without_any_http_call():
    http = FakeHttp(openai_response(json.dumps({"value": "ok"})))
    health = OpenAIProvider(api_key="k", http=http).ready()
    assert health.ok is True
    assert http.calls == []  # no request was made
    assert "not verified" in health.detail


def test_openai_ready_reports_the_missing_api_key():
    health = OpenAIProvider(api_key=None, http=FakeHttp(None)).ready()
    assert health.ok is False and "OPENAI_API_KEY" in health.detail


def test_ollama_ready_is_ok_without_any_http_call():
    http = FakeHttp(FakeResponse({"response": json.dumps({"value": "x"})}))
    health = OllamaProvider(http=http).ready()
    assert health.ok is True
    assert http.calls == []
    assert "not verified" in health.detail


def test_claude_cli_ready_is_ok_when_binary_is_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")
    calls = []

    def unexpected_runner(cmd, **kwargs):
        calls.append(cmd)
        raise AssertionError("ready() must not invoke the CLI")

    health = ClaudeCLIProvider(runner=unexpected_runner).ready()
    assert health.ok is True
    assert calls == []
    assert "not verified" in health.detail


def test_claude_cli_ready_fails_when_binary_is_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: None)
    health = ClaudeCLIProvider().ready()
    assert health.ok is False
    assert "not installed" in health.detail
