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
