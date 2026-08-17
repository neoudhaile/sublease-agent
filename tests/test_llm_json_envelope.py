"""Coverage for the JSON-envelope near-miss recovery in `json_extract`, and
for the three non-structured-output providers (`claude-cli`, `ollama`,
`openai`) against REALISTIC raw model output shapes.

This is the test-gap closure called for by the prompt-envelope bug: the
existing `FakeProvider` in tests/fakes.py never reads the prompt and returns
a pre-validated object, so nothing proved a provider's actual parsing path
recovers from a model that ignores the envelope instruction. These tests
drive the real `extract_json` -> `parse_json_payload` -> `coerce_envelope`
path with strings shaped like what a live model actually returns.
"""
from __future__ import annotations

import json
import subprocess

import pytest
from pydantic import BaseModel, ValidationError

from sublease.errors import ProviderError
from sublease.llm.claude_cli_provider import ClaudeCLIProvider
from sublease.llm.json_extract import coerce_envelope, envelope_field, parse_json_payload
from sublease.llm.ollama_provider import OllamaProvider
from sublease.llm.openai_provider import OpenAIProvider


class Item(BaseModel):
    id: str
    is_seeking: bool


class Batch(BaseModel):
    results: list[Item]


CORRECT_ENVELOPE = json.dumps({
    "results": [
        {"id": "fbpost:1", "is_seeking": True},
        {"id": "fbpost:2", "is_seeking": False},
    ]
})

BARE_ARRAY = json.dumps([
    {"id": "fbpost:1", "is_seeking": True},
    {"id": "fbpost:2", "is_seeking": False},
])

BARE_SINGLE_ITEM = json.dumps({"id": "fbpost:1", "is_seeking": True})

FENCED = f"```json\n{CORRECT_ENVELOPE}\n```"

PROSE_WRAPPED = f"Sure, here is the extraction:\n{CORRECT_ENVELOPE}\nLet me know if you need anything else!"

UNUSABLE = "I'm not able to help with that request."

WRONG_SHAPE = json.dumps({"foo": "bar"})


# --- envelope_field ----------------------------------------------------

def test_envelope_field_finds_the_single_list_field():
    assert envelope_field(Batch) == "results"


def test_envelope_field_is_none_without_exactly_one_list_field():
    class NoList(BaseModel):
        value: str

    class TwoLists(BaseModel):
        a: list[int]
        b: list[int]

    assert envelope_field(NoList) is None
    assert envelope_field(TwoLists) is None


# --- parse_json_payload / coerce_envelope -------------------------------

def test_parse_json_payload_handles_a_top_level_array_correctly():
    """The historical bug: a naive find('{')..rfind('}') scan against a
    top-level array of objects returns a corrupt fragment. This must return
    the full, valid array instead."""
    payload = parse_json_payload(BARE_ARRAY)
    assert payload == json.loads(BARE_ARRAY)


def test_parse_json_payload_strips_markdown_fences():
    assert parse_json_payload(FENCED) == json.loads(CORRECT_ENVELOPE)


def test_parse_json_payload_tolerates_surrounding_prose():
    assert parse_json_payload(PROSE_WRAPPED) == json.loads(CORRECT_ENVELOPE)


def test_parse_json_payload_raises_provider_error_on_unusable_output():
    with pytest.raises(ProviderError):
        parse_json_payload(UNUSABLE)


def test_coerce_envelope_wraps_a_bare_array():
    coerced = coerce_envelope(json.loads(BARE_ARRAY), Batch)
    assert coerced == {"results": json.loads(BARE_ARRAY)}


def test_coerce_envelope_wraps_a_bare_single_item():
    coerced = coerce_envelope(json.loads(BARE_SINGLE_ITEM), Batch)
    assert coerced == {"results": [json.loads(BARE_SINGLE_ITEM)]}


def test_coerce_envelope_leaves_a_correct_envelope_untouched():
    parsed = json.loads(CORRECT_ENVELOPE)
    assert coerce_envelope(parsed, Batch) == parsed


def test_coerce_envelope_does_not_launder_a_genuinely_wrong_shape():
    """Wrapping is not the same as accepting: {"foo": "bar"} gets wrapped as
    a one-item list, but that item still doesn't have the required fields,
    so schema validation - not this function - is what ultimately rejects
    it. Confirm the wrap doesn't accidentally produce something valid."""
    coerced = coerce_envelope(json.loads(WRONG_SHAPE), Batch)
    with pytest.raises(ValidationError):
        Batch.model_validate(coerced)


# --- ClaudeCLIProvider ---------------------------------------------------

def _cli(stdout: str) -> ClaudeCLIProvider:
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout, "")
    return ClaudeCLIProvider(runner=run)


def test_claude_cli_accepts_the_correct_envelope():
    batch = _cli(CORRECT_ENVELOPE).extract_json("p", Batch)
    assert [i.id for i in batch.results] == ["fbpost:1", "fbpost:2"]


def test_claude_cli_recovers_a_bare_array():
    batch = _cli(BARE_ARRAY).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_claude_cli_recovers_a_bare_single_item():
    """This is the exact shape from the production bug report: a one-post
    batch where the model dropped the envelope and returned the item bare."""
    batch = _cli(BARE_SINGLE_ITEM).extract_json("p", Batch)
    assert batch.results == [Item(id="fbpost:1", is_seeking=True)]


def test_claude_cli_recovers_fenced_json():
    batch = _cli(FENCED).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_claude_cli_recovers_prose_wrapped_json():
    batch = _cli(PROSE_WRAPPED).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_claude_cli_still_raises_on_genuinely_unusable_output():
    with pytest.raises(ProviderError):
        _cli(UNUSABLE).extract_json("p", Batch)


def test_claude_cli_still_raises_on_wrong_shape():
    with pytest.raises(ProviderError):
        _cli(WRONG_SHAPE).extract_json("p", Batch)


# --- OllamaProvider -------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class _FakeHttp:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def post(self, url, **kwargs):
        return _FakeResponse({"response": self._response_text})


def _ollama(response_text: str) -> OllamaProvider:
    return OllamaProvider(http=_FakeHttp(response_text))


def test_ollama_accepts_the_correct_envelope():
    batch = _ollama(CORRECT_ENVELOPE).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_ollama_recovers_a_bare_array():
    batch = _ollama(BARE_ARRAY).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_ollama_recovers_fenced_json():
    batch = _ollama(FENCED).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_ollama_recovers_prose_wrapped_json():
    batch = _ollama(PROSE_WRAPPED).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_ollama_still_raises_on_genuinely_unusable_output():
    with pytest.raises(ProviderError):
        _ollama(UNUSABLE).extract_json("p", Batch)


# --- OpenAIProvider --------------------------------------------------------

def _openai_http(content: str):
    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

        def raise_for_status(self):
            pass

    class Http:
        def post(self, url, **kwargs):
            return Resp()

    return Http()


def _openai(content: str) -> OpenAIProvider:
    return OpenAIProvider(api_key="k", http=_openai_http(content))


def test_openai_accepts_the_correct_envelope():
    batch = _openai(CORRECT_ENVELOPE).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_openai_recovers_a_bare_array():
    batch = _openai(BARE_ARRAY).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_openai_recovers_fenced_json():
    """OpenAI's JSON mode guarantees valid JSON syntax, not markdown-free
    output; some models still wrap their JSON-mode response in fences."""
    batch = _openai(FENCED).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_openai_recovers_prose_wrapped_json():
    batch = _openai(PROSE_WRAPPED).extract_json("p", Batch)
    assert len(batch.results) == 2


def test_openai_still_raises_on_wrong_shape():
    with pytest.raises(ProviderError):
        _openai(WRONG_SHAPE).extract_json("p", Batch)
