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


def test_fake_provider_longest_marker_wins_on_substring_collision():
    fake = FakeProvider(responses={
        "fbpost:1": {"value": "post-1"},
        "fbpost:10": {"value": "post-10"},
    })
    assert fake.extract_json("batch prompt with fbpost:10 inside", Payload).value == "post-10"
    assert fake.extract_json("batch prompt with fbpost:1 inside", Payload).value == "post-1"


def test_fake_provider_raises_on_equal_length_marker_ambiguity():
    fake = FakeProvider(responses={
        "fbpost:1": {"value": "a"},
        "fbpost:2": {"value": "b"},
    })
    with pytest.raises(ProviderError, match="ambiguous"):
        fake.extract_json("prompt mentions fbpost:1 and fbpost:2", Payload)


def test_fake_provider_wraps_schema_mismatch_in_provider_error():
    fake = FakeProvider(responses={"MARKER": {"not_the_value_field": "x"}})
    with pytest.raises(ProviderError, match="MARKER"):
        fake.extract_json("prompt containing MARKER", Payload)


def test_fake_provider_fail_on_takes_precedence_over_matching_response():
    fake = FakeProvider(
        responses={"fbpost:1": {"value": "x"}},
        fail_on={"fbpost:1"},
    )
    with pytest.raises(ProviderError):
        fake.extract_json("prompt with fbpost:1 inside", Payload)
