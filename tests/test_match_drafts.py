# tests/test_match_drafts.py
import locale
from datetime import date
import pytest
from sublease.match.drafts import build_draft, format_span, sanitize_for_messenger
from sublease.match.types import Candidate

TEMPLATE = "Hi {first_name}! Saw your post in {group} — I have a room for {their_dates}."


def cand(name="Emma Stone", start=date(2026, 8, 18), end=date(2026, 9, 8),
         group="NYC Sublets"):
    return Candidate(post_id="fbpost:1", person_key="k", name=name,
                     fit="full-window", days_covered=22, wants_start=start,
                     wants_end=end, group_name=group)


@pytest.mark.parametrize("trap,safe", [
    ("8)", "8 )"), ("8-)", "8 )"), (":)", ": )"), (":(", ": ("),
    (":P", ": P"), (":D", ": D"), (";)", "; )"), (":/", ": /"),
])
def test_every_emoticon_trap_is_defused(trap, safe):
    assert sanitize_for_messenger(f"call me at {trap} ok") == f"call me at {safe} ok"


def test_sanitizer_leaves_ordinary_text_alone():
    text = "The room is available August 18 through September 8."
    assert sanitize_for_messenger(text) == text


def test_sanitizer_handles_several_traps_in_one_message():
    assert sanitize_for_messenger("8) and :(") == "8 ) and : ("


def test_span_with_both_dates():
    assert format_span(date(2026, 8, 18), date(2026, 9, 8)) == "Aug 18 – Sep 8"


def test_span_with_only_a_start():
    assert format_span(date(2026, 8, 22), None) == "from Aug 22"


def test_span_with_only_an_end():
    assert format_span(None, date(2026, 9, 1)) == "until Sep 1"


def test_span_with_neither_date():
    assert format_span(None, None) == "your dates"


def test_draft_substitutes_the_first_name_only():
    assert "Hi Emma!" in build_draft(TEMPLATE, cand())
    assert "Stone" not in build_draft(TEMPLATE, cand())


def test_draft_substitutes_the_group_and_dates():
    draft = build_draft(TEMPLATE, cand())
    assert "in NYC Sublets" in draft
    assert "Aug 18 – Sep 8" in draft


def test_draft_falls_back_when_the_name_is_missing():
    assert build_draft(TEMPLATE, cand(name=None)).startswith("Hi there!")


def test_draft_falls_back_when_the_group_is_missing():
    assert "in the group" in build_draft(TEMPLATE, cand(group=None))


def test_draft_output_is_always_sanitized():
    template = "Hi {first_name}, unit 8) is free."
    assert "8 )" in build_draft(template, cand())


def test_a_template_with_no_placeholders_passes_through():
    assert build_draft("Room available, message me.", cand()) == \
        "Room available, message me."


# --- Fix wave 2026-08-15 ----------------------------------------------------
# Finding 2: `_short` used to render the month with `strftime('%b')`, which
# is locale-dependent (LC_TIME), not just platform-dependent. A draft built
# on a machine set to a non-English locale would silently go out with a
# non-English month abbreviation. Drafts are always English, so the month
# must not move when the process locale does.

def test_month_abbreviation_is_english_regardless_of_process_locale():
    try:
        locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
    except locale.Error:
        pytest.skip("de_DE.UTF-8 locale not installed on this machine")
    try:
        assert format_span(date(2026, 8, 18), date(2026, 9, 8)) == "Aug 18 – Sep 8"
    finally:
        locale.setlocale(locale.LC_TIME, "C")
