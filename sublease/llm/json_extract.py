"""Shared JSON-envelope handling for providers without native structured output.

`AnthropicProvider` gets its shape enforced server-side by `messages.parse`.
`ClaudeCLIProvider`, `OllamaProvider`, and `OpenAIProvider` do not: the CLI and
Ollama return free-form text, and OpenAI's "JSON mode" guarantees valid JSON
syntax, not a specific schema. Models drift from instructions - they wrap the
payload in markdown fences, add a sentence of prose before or after it, or
(most commonly) return the bare list/object without the envelope the prompt
asked for. This module recovers from those near-misses so one stray response
doesn't fail an entire batch; anything that still can't be reconciled with the
schema raises `ProviderError`, so the runner's bisect recovery isolates the
offending post exactly as it does for an outright provider failure.

`envelope_field` is also imported by `sublease.extract.prompts`, so the text
telling the model what key to use and the coercion logic here that expects
that key both read it from the same place - the Pydantic schema - and cannot
drift apart.
"""
from __future__ import annotations

import json
import re
from typing import get_origin

from pydantic import BaseModel

from sublease.errors import ProviderError

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def envelope_field(schema: type[BaseModel]) -> str | None:
    """The name of `schema`'s one list-typed field, or None if it doesn't have
    exactly one. Every batch schema in this package (`ExtractionBatch`,
    `EnrichmentBatch`, `OfferBatch`) has exactly one such field: `results`.
    A schema with zero or more than one list field has no single natural
    envelope key, so callers leave it alone rather than guess.
    """
    list_fields = [
        name for name, field in schema.model_fields.items()
        if get_origin(field.annotation) is list
    ]
    return list_fields[0] if len(list_fields) == 1 else None


def _strip_fences(text: str) -> str:
    """Unwrap a ```json ... ``` or ``` ... ``` fenced block, if present."""
    match = _FENCE_RE.search(text)
    return match.group(1).strip() if match else text


def _find_json_value(text: str) -> str:
    """Locate the first balanced top-level JSON object or array in `text`,
    tolerating prose before and after it.

    This balances nested braces/brackets and skips over string contents, so
    it handles a top-level array correctly - a naive `find("{")..rfind("}")`
    scan against `[{"a": 1}, {"a": 2}]` would return the corrupt fragment
    `{"a": 1}, {"a": 2}` (first `{` to last `}`), which is exactly the trap
    named in the bug report.
    """
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        raise ProviderError(f"no JSON object or array in output: {text[:200]}")

    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ProviderError(f"unbalanced JSON object or array in output: {text[:200]}")


def parse_json_payload(text: str) -> object:
    """Recover a JSON value from raw model output.

    Strips markdown fences if present, then locates the first balanced
    top-level object or array even with prose before or after it. Returns
    the parsed Python value (a dict or a list). Raises `ProviderError` if no
    valid JSON can be found at all.
    """
    candidate = _find_json_value(_strip_fences(text))
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"could not parse JSON in output: {text[:200]}") from exc


def coerce_envelope(payload: object, schema: type[BaseModel]) -> object:
    """If `payload` is missing the envelope `schema` expects, wrap it.

    Two near-misses are recovered, both observed from real model drift:
      * a bare array, where `{<field>: [...]}` was expected - wrapped as-is.
      * a bare single item object (no array at all), e.g. because the model
        was asked about one post and dropped the envelope entirely - wrapped
        as a one-element array.

    Anything else - including a dict that already carries the envelope key,
    or a schema with no single natural list field - is returned unchanged,
    so `schema.model_validate` sees it as-is. A payload that doesn't fit
    either near-miss (e.g. `{"foo": "bar"}`, or a bare item missing required
    fields) is *not* silently accepted: it is coerced or passed through, but
    still has to pass real schema validation, so genuinely wrong output still
    raises.
    """
    field = envelope_field(schema)
    if field is None:
        return payload
    if isinstance(payload, list):
        return {field: payload}
    if isinstance(payload, dict) and field not in payload:
        return {field: [payload]}
    return payload
