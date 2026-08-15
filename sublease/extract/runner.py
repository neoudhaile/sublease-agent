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
        # Validate that result ids match the sent ids exactly
        sent_ids = {p["id"] for p in posts}
        result_ids = {item.id for item in batch.results}
        if sent_ids != result_ids:
            missing = sent_ids - result_ids
            unexpected = result_ids - sent_ids
            raise ProviderError(
                f"result ids do not match sent ids: missing {missing}, unexpected {unexpected}")
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
        # Validate that result ids match the sent ids exactly
        sent_ids = {p["id"] for p in posts}
        result_ids = {item.id for item in batch.results}
        if sent_ids != result_ids:
            missing = sent_ids - result_ids
            unexpected = result_ids - sent_ids
            raise ProviderError(
                f"result ids do not match sent ids: missing {missing}, unexpected {unexpected}")
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
