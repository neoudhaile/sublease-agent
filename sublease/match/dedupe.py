"""Collapse many posts into one person.

The same human cross-posts to every group they can find, and reposts for reach.
Keyed on (name, requested dates) rather than on the post id, because the post id
is exactly what differs between those sightings.

Ported from reference/pipeline/filter_rank.py:169-180.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sublease.match.types import Candidate

_UNIX_TS = re.compile(r"\d+")


def person_key(
    name: str | None,
    start: date | None,
    end: date | None,
    post_id: str | None = None,
) -> str:
    """Build the identity key a set of sightings collapse onto.

    When `name` is missing we cannot tell two different anonymous posters
    apart, and merging them would silently drop one from the shortlist.
    Rather than guess, `post_id` (unique per post) is folded into the key so
    every nameless post stays its own candidate. Named posters are keyed on
    (name, dates) only, exactly as before, so cross-posting still collapses.
    """
    who = (name or "").strip().lower()
    base = f"{who}|{start.isoformat() if start else ''}|{end.isoformat() if end else ''}"
    if not who and post_id:
        return f"{base}|{post_id}"
    return base


def parse_post_date_epoch(raw: str | None) -> float | None:
    """Best-effort parse of a free-text post_date into a comparable epoch.

    Handles ISO-8601 dates/datetimes and bare unix timestamps. Anything else
    (human strings like "Aug 9", empty text, None) returns None so the caller
    can treat it as the oldest possible post rather than raising or winning
    a lexicographic comparison it has no business winning.

    Public: this is the one date-aware parser for `post_date` in the whole
    package. `ranking.py` reuses it (via `recency_sort_key`) rather than
    sorting the same field as a raw string a second time.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if _UNIX_TS.fullmatch(text):
        try:
            return float(text)
        except (ValueError, OverflowError):
            return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def recency_sort_key(candidate: Candidate) -> tuple[float, str]:
    """Sort key for "most recent post first". Shared by dedupe and ranking.

    Unparseable/missing dates sort as oldest; post_id gives a deterministic
    tiebreak instead of leaving genuinely-tied candidates in input order.
    """
    epoch = parse_post_date_epoch(candidate.post_date)
    return (epoch if epoch is not None else float("-inf"), candidate.post_id or "")


def dedupe_people(candidates: list[Candidate]) -> list[Candidate]:
    """Keep the newest post per person; fold the rest into `also_posted_in`."""
    newest_first = sorted(candidates, key=recency_sort_key, reverse=True)

    kept: dict[str, Candidate] = {}
    for candidate in newest_first:
        seen = kept.get(candidate.person_key)
        if seen is None:
            kept[candidate.person_key] = candidate
        elif candidate.group_name and candidate.group_name not in seen.also_posted_in:
            seen.also_posted_in.append(candidate.group_name)
    return list(kept.values())
