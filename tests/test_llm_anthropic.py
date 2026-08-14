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


def test_extract_json_wraps_client_construction_error(monkeypatch):
    """Client construction errors should be wrapped as ProviderError."""
    def mock_anthropic_raises(*args, **kwargs):
        raise RuntimeError("malformed ANTHROPIC_BASE_URL")

    monkeypatch.setattr("anthropic.Anthropic", mock_anthropic_raises)
    provider = AnthropicProvider(client=None, api_key="test-key")

    with pytest.raises(ProviderError, match="malformed ANTHROPIC_BASE_URL"):
        provider.extract_json("p", Payload)


def test_health_handles_client_construction_error(monkeypatch):
    """health() should return ProviderHealth instead of raising on construction errors."""
    def mock_anthropic_raises(*args, **kwargs):
        raise RuntimeError("malformed ANTHROPIC_BASE_URL")

    monkeypatch.setattr("anthropic.Anthropic", mock_anthropic_raises)
    provider = AnthropicProvider(client=None, api_key="test-key")

    health = provider.health()
    assert health.ok is False
    assert "malformed ANTHROPIC_BASE_URL" in health.detail
