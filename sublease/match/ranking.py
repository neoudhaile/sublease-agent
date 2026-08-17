"""Join extractions, enrichments, and posts into a ranked candidate list.

Ported from reference/pipeline/filter_rank.py:126-214. The one behavioural
change is that every rule now reads from the profile rather than a constant.

Ordering is a two-pass stable sort, exactly as the prototype did it: sort by
recency first, then by (tier, days covered, fit). Python's sort is stable, so the
recency pass survives as the tie-breaker within each tier.
"""
from __future__ import annotations

from datetime import date

from sublease.match.dedupe import dedupe_people, person_key, recency_sort_key
from sublease.match.drafts import build_draft
from sublease.match.tiering import tier_for
from sublease.match.types import FIT_ORDER, TIER_ORDER, Candidate
from sublease.match.window import classify
from sublease.profile.models import Profile

POST_TEXT_LIMIT = 500


def _parse(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def rank(posts: dict[str, dict], extractions: list[dict],
         enrichments: dict[str, dict], profile: Profile) -> list[Candidate]:
    w_start, w_end = profile.window.start, profile.window.end
    window_days = profile.window.days

    candidates: list[Candidate] = []
    for row in extractions:
        if not row.get("is_seeking"):
            continue
        post = posts.get(row["post_id"])
        if post is None:
            continue

        start = _parse(row.get("start_date"))
        end = _parse(row.get("end_date"))
        fit, days = classify(start, end, w_start, w_end)
        if fit is None:
            continue

        enriched = enrichments.get(row["post_id"], {})
        name = post.get("author_name")
        candidates.append(Candidate(
            post_id=row["post_id"],
            person_key=person_key(name, start, end, row["post_id"]),
            name=name,
            fit=fit,
            days_covered=days,
            wants_start=start,
            wants_end=end,
            profile_url=post.get("author_url"),
            post_url=post.get("url"),
            group_name=post.get("group_name"),
            post_date=post.get("posted_at"),
            budget=row.get("budget"),
            confidence=row.get("confidence"),
            date_text=row.get("date_text"),
            people_in_one_room=enriched.get("people_in_one_room", 1),
            wants_multiple_rooms=bool(enriched.get("wants_multiple_rooms")),
            gender=enriched.get("gender"),
            occupants=(enriched.get("group_size")
                       or enriched.get("people_in_one_room") or 1),
            post_text=(post.get("text") or "")[:POST_TEXT_LIMIT].replace("\n", " "),
        ))

    candidates = dedupe_people(candidates)

    for candidate in candidates:
        candidate.tier, candidate.tier_reason = tier_for(
            candidate.facts(), profile.constraints, window_days)
        candidate.draft = build_draft(profile.templates.outreach_message, candidate)

    candidates.sort(key=recency_sort_key, reverse=True)
    candidates.sort(key=lambda c: (TIER_ORDER.get(c.tier or "", 9),
                                   -c.days_covered,
                                   FIT_ORDER.get(c.fit, 9)))
    return candidates


def to_rows(candidates: list[Candidate]) -> list[dict]:
    """Shape candidates for CandidateRepo.sync."""
    return [
        {
            "person_key": c.person_key,
            "post_id": c.post_id,
            "also_posted_in": c.also_posted_in,
            "tier": c.tier,
            "tier_reason": c.tier_reason,
            "fit": c.fit,
            "days_covered": c.days_covered,
            "wants_start": c.wants_start.isoformat() if c.wants_start else None,
            "wants_end": c.wants_end.isoformat() if c.wants_end else None,
            "draft": c.draft,
        }
        for c in candidates
    ]
