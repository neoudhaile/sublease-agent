"""Prompt construction.

Both prompts are ported from the prototype, with one change: every date fact is
computed from the reference date the caller passes rather than written as a
literal.
"""
from __future__ import annotations

import json
from datetime import date

from sublease.extract.dates import labor_day

EXTRACTION_TRUNCATE = 1500
ENRICHMENT_TRUNCATE = 1200


def build_extraction_prompt(posts: list[dict], today: date) -> str:
    """Pass 1: is this person seeking, and for which dates?"""
    holiday = labor_day(today.year)
    header = f"""\
You extract structured data from Facebook group posts about housing.
Today's date is {today.isoformat()}. Assume the year {today.year} for any date
without a year. Labor Day {today.year} is {holiday.strftime('%B %-d')}.

For each post return an object with:
- "id": copied verbatim from the input
- "is_seeking": true ONLY if the author is LOOKING FOR a place to stay for
  themselves (or someone they represent). Posts OFFERING/listing a room,
  apartment, or sublet are false.
- "start_date": "YYYY-MM-DD" or null - start of the timeframe they need housing
- "end_date": "YYYY-MM-DD" or null
- "date_text": the verbatim phrase they used for dates, or null
- "budget": their stated budget as written (e.g. "$1500/mo"), or null
- "confidence": "high" | "medium" | "low" for the date interpretation

Interpret fuzzy phrases sensibly: "early August" ~ Aug 1-7, "mid-August" ~ Aug 15,
"late August" / "end of August" ~ Aug 25-31, "the month of August" = Aug 1-31,
"through Labor Day" = ending {holiday.isoformat()}. If they give only a start
("from Aug 20"), leave end_date null. If there is no timeframe at all, both null
with confidence "low".

Return one object per post, in the same order as the input.

POSTS:
"""
    payload = [{"id": p["id"], "text": (p["text"] or "")[:EXTRACTION_TRUNCATE]}
               for p in posts]
    return header + json.dumps(payload, ensure_ascii=False)


def build_enrichment_prompt(posts: list[dict]) -> str:
    """Pass 2: who would actually move in? Seekers only.

    The two-separate-rooms distinction is load-bearing: someone who needs two
    rooms is still one person per room, which is not the dealbreaker a couple
    sharing one room is.
    """
    header = """\
You read housing posts from people SEEKING a place, and extract who would
actually move in. For each post return an object with:
- "id": copied verbatim from the input
- "people_in_one_room": how many people would SHARE A SINGLE ROOM. A couple, or
  two people who explicitly want to live together in one room = 2. A solo
  searcher = 1. CRITICAL: someone looking for TWO SEPARATE ROOMS or a 2-bedroom
  for themselves + a friend is 1 PER ROOM - return 1 for them, and set
  "wants_multiple_rooms": true.
- "wants_multiple_rooms": true if they need 2+ separate rooms/bedrooms
- "group_size": total people who would move in (1 for solo, 2 for a couple or pair)
- "gender": "male" | "female" | null - ONLY when clearly stated or unambiguous
  from self-description ("I'm a 23 year old guy", "she/her", "girl looking").
  NEVER guess from the person's name. Use null when unclear.

Return one object per post, in the same order as the input.

POSTS:
"""
    payload = [{"id": p["id"], "text": (p["text"] or "")[:ENRICHMENT_TRUNCATE]}
               for p in posts]
    return header + json.dumps(payload, ensure_ascii=False)
