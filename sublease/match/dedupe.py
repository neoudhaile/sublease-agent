"""Collapse many posts into one person.

The same human cross-posts to every group they can find, and reposts for reach.
Keyed on (name, requested dates) rather than on the post id, because the post id
is exactly what differs between those sightings.

Ported from reference/pipeline/filter_rank.py:169-180.
"""
from __future__ import annotations

from datetime import date

from sublease.match.types import Candidate


def person_key(name: str | None, start: date | None, end: date | None) -> str:
    who = (name or "").strip().lower()
    return f"{who}|{start.isoformat() if start else ''}|{end.isoformat() if end else ''}"


def dedupe_people(candidates: list[Candidate]) -> list[Candidate]:
    """Keep the newest post per person; fold the rest into `also_posted_in`."""
    newest_first = sorted(candidates, key=lambda c: str(c.post_date or ""), reverse=True)

    kept: dict[str, Candidate] = {}
    for candidate in newest_first:
        seen = kept.get(candidate.person_key)
        if seen is None:
            kept[candidate.person_key] = candidate
        elif candidate.group_name and candidate.group_name not in seen.also_posted_in:
            seen.also_posted_in.append(candidate.group_name)
    return list(kept.values())
