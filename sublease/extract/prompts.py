"""Prompt construction.

Both prompts are ported from the prototype, with one change: every date fact is
computed from the reference date the caller passes rather than written as a
literal.

Every builder also states the JSON envelope the response must use. Only
`AnthropicProvider` gets that shape enforced server-side (`messages.parse`);
`ClaudeCLIProvider`, `OllamaProvider`, and `OpenAIProvider` depend entirely on
the model reading and following this instruction, so it has to be explicit
and unambiguous - see `_envelope_instructions` below.
"""
from __future__ import annotations

import json
from datetime import date

from pydantic import BaseModel

from sublease.extract.dates import labor_day
from sublease.extract.schemas import EnrichmentBatch, ExtractionBatch, OfferBatch
from sublease.llm.json_extract import envelope_field

EXTRACTION_TRUNCATE = 1500
ENRICHMENT_TRUNCATE = 1200
OFFER_TRUNCATE = 1500


def _labor_day_str(holiday: date) -> str:
    """Render "<Month> <day>" without a leading zero, e.g. "September 6".

    `strftime('%-d')` is a glibc/BSD extension that raises ValueError on
    Windows, so the day number is interpolated directly instead.
    """
    return f"{holiday.strftime('%B')} {holiday.day}"


def _envelope_instructions(schema: type[BaseModel]) -> str:
    """Tell the model exactly what envelope to return, keyed off `schema`
    itself so this text and the Pydantic model it describes cannot drift
    apart - there is no key name hardcoded here to fall out of sync.
    """
    field = envelope_field(schema)
    assert field is not None, f"{schema.__name__} has no single list field"
    return (
        f'Return a single JSON object with exactly one key, "{field}", whose '
        "value is a JSON array containing one object per input post, in the "
        "same order as the input. Do not wrap the JSON in markdown code "
        "fences. Do not include any prose, explanation, or text before or "
        "after the JSON object - the response must contain nothing but the "
        "JSON object itself."
    )


def build_extraction_prompt(posts: list[dict], today: date) -> str:
    """Pass 1: is this person seeking, and for which dates?"""
    holiday = labor_day(today.year)
    header = f"""\
You extract structured data from Facebook group posts about housing.
Today's date is {today.isoformat()}. Assume the year {today.year} for any date
without a year. Labor Day {today.year} is {_labor_day_str(holiday)}.

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

{_envelope_instructions(ExtractionBatch)}

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
    header = f"""\
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

{_envelope_instructions(EnrichmentBatch)}

POSTS:
"""
    payload = [{"id": p["id"], "text": (p["text"] or "")[:ENRICHMENT_TRUNCATE]}
               for p in posts]
    return header + json.dumps(payload, ensure_ascii=False)


def build_offer_prompt(posts: list[dict], today: date) -> str:
    """Pass 3: what is this listing offering, and for how much?

    Runs over posts the extraction pass already marked as NOT seeking — i.e.
    posts offering a room, apartment, or sublet rather than looking for one.
    The caller decides which posts qualify; this prompt does not re-litigate
    intent.
    """
    holiday = labor_day(today.year)
    header = f"""\
You extract structured pricing data from Facebook group posts that are
OFFERING a room, apartment, or sublet (as opposed to someone looking for one).
Today's date is {today.isoformat()}. Assume the year {today.year} for any date
without a year. Labor Day {today.year} is {_labor_day_str(holiday)}.

For each post return an object with:
- "id": copied verbatim from the input
- "price_amount": the numeric price as stated (e.g. 1400 for "$1400/mo"), or
  null if no price is stated anywhere in the post
- "price_unit": "night" | "week" | "month" | "period" - the unit the price
  was stated in. Use "period" ONLY when the price is a lump sum for the whole
  stay (e.g. "$1800 for the 3 weeks", "$1800 total") rather than a recurring
  rate. "period" is only useful together with dates, so whenever you use it,
  also extract start_date/end_date if the post states or implies them.
- "currency": the currency, e.g. "USD" - assume "USD" when a $ sign is used
  and no other currency is stated
- "neighborhood": the neighborhood or area exactly AS WRITTEN in the post -
  do not normalize it, expand abbreviations, or guess a canonical name; null
  if none is mentioned
- "unit_type": "room" if a single room/bedroom within a shared apartment is
  being offered, "whole_unit" if the entire apartment/unit is being offered
- "bedrooms": the number of bedrooms in the unit, if stated, else null
- "bath": "shared" or "private" if stated, else null
- "furnished": true/false if stated or clearly implied, else null
- "start_date": "YYYY-MM-DD" or null - when the listing becomes available
- "end_date": "YYYY-MM-DD" or null - when it stops being available

Interpret fuzzy phrases sensibly: "early August" ~ Aug 1-7, "mid-August" ~
Aug 15, "late August" / "end of August" ~ Aug 25-31, "the month of August" =
Aug 1-31, "through Labor Day" = ending {holiday.isoformat()}.

{_envelope_instructions(OfferBatch)}

POSTS:
"""
    payload = [{"id": p["id"], "text": (p["text"] or "")[:OFFER_TRUNCATE]}
               for p in posts]
    return header + json.dumps(payload, ensure_ascii=False)
