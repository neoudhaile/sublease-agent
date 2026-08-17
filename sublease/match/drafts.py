"""Render the per-candidate outreach draft.

Ported from reference/pipeline/filter_rank.py:94-123.

The sanitizer is not cosmetic. Facebook's composer rewrites certain ASCII
sequences into emoji as you type — "8)" becomes a sunglasses face — so a draft
that mentions "unit 8) is free" arrives as gibberish. The prototype also found
that the composer turns lines beginning "- " into double bullets, which is why
listing copy is written in sentences.
"""
from __future__ import annotations

from datetime import date

from sublease.match.types import Candidate

EMOTICON_TRAPS = {
    "8)": "8 )", "8-)": "8 )", ":)": ": )", ":(": ": (",
    ":P": ": P", ":D": ": D", ";)": "; )", ":/": ": /",
}

# Explicit table rather than `strftime('%b')`: that format code renders in
# the process's LC_TIME locale, so an outreach draft sent from a machine set
# to a non-English locale would silently go out in the wrong language. The
# drafts this package sends are always in English, independent of where the
# tool happens to run.
_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def sanitize_for_messenger(text: str) -> str:
    for trap, safe in EMOTICON_TRAPS.items():
        text = text.replace(trap, safe)
    return text


def _short(day: date) -> str:
    return f"{_MONTH_ABBR[day.month]} {day.day}"


def format_span(start: date | None, end: date | None) -> str:
    if start and end:
        return f"{_short(start)} – {_short(end)}"
    if start:
        return f"from {_short(start)}"
    if end:
        return f"until {_short(end)}"
    return "your dates"


def build_draft(template: str, candidate: Candidate) -> str:
    name = (candidate.name or "").strip()
    first_name = name.split()[0] if name else "there"
    text = (template
            .replace("{first_name}", first_name)
            .replace("{their_dates}", format_span(candidate.wants_start,
                                                  candidate.wants_end))
            .replace("{group}", candidate.group_name or "the group"))
    return sanitize_for_messenger(text)
