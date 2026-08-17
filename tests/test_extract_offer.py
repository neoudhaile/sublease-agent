from datetime import date

import pytest
from pydantic import ValidationError

from sublease.extract.prompts import build_offer_prompt
from sublease.extract.runner import (
    parse_int, parse_price_amount, price_hint_matches, run_offer_extraction,
)
from sublease.extract.schemas import OfferBatch
from sublease.store.db import connect, migrate
from sublease.store.repositories import OFFER_COLUMNS, OfferRepo, PostRepo
from tests.fakes import FakeProvider

TODAY = date(2026, 8, 11)


def post(pid, text):
    return {"id": pid, "text": text}


def rows_by_id(rows):
    return {r["post_id"]: r for r in rows}


# --- prefilter -------------------------------------------------------------

def test_posts_with_no_price_token_never_reach_the_model():
    provider = FakeProvider()
    rows = run_offer_extraction(
        [post("fbpost:1", "Room available in East Village, message me for details")],
        provider, today=TODAY)
    assert provider.calls == []
    row = rows_by_id(rows)["fbpost:1"]
    assert row["model"] is None
    assert row["error"] is None


def test_price_hint_matches_common_price_forms():
    for text in ["$1400/mo", "$60/night", "1400 per month", "$350 / week", "60 USD"]:
        assert price_hint_matches(text) is True, text


def test_price_hint_rejects_plain_numbers_with_no_price_context():
    for text in ["Move in Aug 20, 3 bedroom apt", "call me at 555 1234", "2 people"]:
        assert price_hint_matches(text) is False, text


def test_price_hint_catches_ordinary_no_symbol_phrasings():
    """Recall is the whole point of this prefilter: a false negative drops a
    priced post from the comp set permanently (extraction is write-once and
    cached by post id), while a false positive costs one wasted model call.
    These are all plausible FB-post phrasings that a precision-leaning regex
    would miss."""
    for text in [
        "1400 a month", "1400 monthly", "rent is 1400 monthly",
        "1400$", "$1400", "asking 1,400 for the room",
        "1.4k a month", "60 a night", "60 nightly",
        "350 a week", "350 weekly", "1400pm",
    ]:
        assert price_hint_matches(text) is True, text


def test_price_hint_still_skips_genuinely_price_free_posts():
    """Widening for recall must not become 'match everything' — that would
    waste a model call on every post, defeating the prefilter's purpose."""
    for text in [
        "Move in Aug 20, 3 bedroom apt", "call me at 555 1234", "2 people",
        "Looking for a room near campus, flexible on move-in date",
        "3 bedroom, 2 bath, available now", "text me for details",
    ]:
        assert price_hint_matches(text) is False, text


# --- happy path / row shaping ----------------------------------------------

def test_priced_offer_is_extracted_and_shaped_for_the_repository():
    provider = FakeProvider(responses={"OfferBatch:fbpost:1": {"results": [
        {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month",
         "currency": "USD", "neighborhood": "East Village", "unit_type": "room",
         "bedrooms": "2", "bath": "shared", "furnished": True,
         "start_date": "2026-08-18", "end_date": "2026-09-08"},
    ]}})
    rows = run_offer_extraction(
        [post("fbpost:1", "Room $1400/mo in East Village, 2BR shared bath")],
        provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    assert row["price_amount"] == 1400.0
    assert row["price_unit"] == "month"
    assert row["neighborhood"] == "East Village"
    assert row["unit_type"] == "room"
    assert row["bedrooms"] == 2
    assert row["bath"] == "shared"
    assert row["furnished"] is True
    assert row["start_date"] == "2026-08-18"
    assert row["end_date"] == "2026-09-08"
    assert row["model"] == "fake-model"
    assert row["error"] is None


def test_extracted_row_keys_exactly_match_offer_repo_columns():
    """A key mismatch against OFFER_COLUMNS is silent (repo uses .get() per
    column), so this pins the row shape against the real column list rather
    than a hand-copied one."""
    provider = FakeProvider(responses={"OfferBatch:fbpost:1": {"results": [
        {"id": "fbpost:1", "price_amount": "60", "price_unit": "night"},
    ]}})
    rows = run_offer_extraction(
        [post("fbpost:1", "$60/night room")], provider, today=TODAY)
    row = rows[0]
    non_computed = set(OFFER_COLUMNS) - {"nightly_price"}
    assert non_computed <= row.keys()
    assert set(row.keys()) <= set(OFFER_COLUMNS)


def test_price_amount_string_forms_are_coerced_to_float():
    assert parse_price_amount("$1,400.50") == 1400.50
    assert parse_price_amount(1500) == 1500.0
    assert parse_price_amount(None) is None
    assert parse_price_amount("no price here") is None


def test_parse_int_extracts_leading_digits_and_rejects_junk():
    assert parse_int("2") == 2
    assert parse_int("2 bedrooms") == 2
    assert parse_int(3) == 3
    assert parse_int(None) is None
    assert parse_int("studio") is None


# --- every post produces exactly one row ------------------------------------

def test_every_post_gets_exactly_one_row_even_when_some_fail():
    posts = [post("fbpost:1", "$1400/mo POISON"), post("fbpost:2", "$1400/mo good"),
             post("fbpost:3", "no price mentioned at all")]
    provider = FakeProvider(
        responses={"OfferBatch:fbpost:2": {"results": [
            {"id": "fbpost:2", "price_amount": "1400", "price_unit": "month"}]}},
        fail_on={"POISON"})
    rows = run_offer_extraction(posts, provider, today=TODAY, batch_size=1)
    assert sorted(r["post_id"] for r in rows) == ["fbpost:1", "fbpost:2", "fbpost:3"]
    by_id = rows_by_id(rows)
    assert by_id["fbpost:1"]["error"] is not None
    assert by_id["fbpost:2"]["error"] is None
    assert by_id["fbpost:3"]["model"] is None  # prefiltered, never reached provider


# --- bisect on failure -------------------------------------------------------

def test_a_failing_batch_bisects_to_isolate_the_offending_post():
    good1 = post("fbpost:1", "$1400/mo good listing")
    bad = post("fbpost:2", "$1400/mo POISON")
    good2 = post("fbpost:3", "$1400/mo also good")
    provider = FakeProvider(
        responses={
            "OfferBatch:fbpost:1": {"results": [
                {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month"}]},
            "OfferBatch:fbpost:3": {"results": [
                {"id": "fbpost:3", "price_amount": "1400", "price_unit": "month"}]},
        },
        fail_on={"POISON"})
    rows = rows_by_id(run_offer_extraction([good1, bad, good2], provider,
                                            today=TODAY, batch_size=3))
    assert rows["fbpost:1"]["price_amount"] == 1400.0
    assert rows["fbpost:1"]["error"] is None
    assert rows["fbpost:3"]["price_amount"] == 1400.0
    assert rows["fbpost:3"]["error"] is None
    assert rows["fbpost:2"]["price_amount"] is None
    assert "fake failure" in rows["fbpost:2"]["error"]
    # a call was made per bisected sub-batch, proving the split actually happened
    assert len(provider.calls) > 1


def test_bisect_isolates_offender_without_dropping_the_others_in_a_larger_batch():
    posts = [post(f"fbpost:{n}", f"$1{n}00/mo good listing number {n}")
             for n in range(1, 6)]
    posts[3] = post("fbpost:4", "$1400/mo POISON")
    responses = {
        f"OfferBatch:{p['id']}": {"results": [
            {"id": p["id"], "price_amount": "1400", "price_unit": "month"}]}
        for p in posts if p["id"] != "fbpost:4"
    }
    provider = FakeProvider(responses=responses, fail_on={"POISON"})
    rows = rows_by_id(run_offer_extraction(posts, provider, today=TODAY, batch_size=5))
    assert sorted(rows.keys()) == [f"fbpost:{n}" for n in range(1, 6)]
    for pid in ["fbpost:1", "fbpost:2", "fbpost:3", "fbpost:5"]:
        assert rows[pid]["error"] is None
    assert rows["fbpost:4"]["error"] is not None


# --- id-set validation --------------------------------------------------------

def test_duplicated_and_missing_ids_are_treated_as_a_batch_failure():
    posts = [post("fbpost:1", "$1400/mo one"), post("fbpost:2", "$1500/mo two"),
             post("fbpost:3", "$1600/mo three")]
    # right count (3), but fbpost:1 duplicated and fbpost:3 missing
    provider = FakeProvider(responses={"OfferBatch:POSTS": {"results": [
        {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month"},
        {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month"},
        {"id": "fbpost:2", "price_amount": "1500", "price_unit": "month"},
    ]}})
    rows = rows_by_id(run_offer_extraction(posts, provider, today=TODAY, batch_size=3))
    assert sorted(rows.keys()) == ["fbpost:1", "fbpost:2", "fbpost:3"]
    for pid in rows:
        assert rows[pid]["error"] is not None


def test_unknown_id_in_the_response_is_treated_as_a_batch_failure():
    posts = [post("fbpost:1", "$1400/mo one"), post("fbpost:2", "$1500/mo two")]
    provider = FakeProvider(responses={"OfferBatch:POSTS": {"results": [
        {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month"},
        {"id": "fbpost:999", "price_amount": "1500", "price_unit": "month"},
    ]}})
    rows = rows_by_id(run_offer_extraction(posts, provider, today=TODAY, batch_size=2))
    assert sorted(rows.keys()) == ["fbpost:1", "fbpost:2"]
    assert rows["fbpost:1"]["error"] is not None
    assert rows["fbpost:2"]["error"] is not None
    assert "fbpost:999" not in rows


def test_a_short_model_response_is_treated_as_a_batch_failure():
    posts = [post("fbpost:1", "$1400/mo one"), post("fbpost:2", "$1500/mo two")]
    provider = FakeProvider(responses={"OfferBatch:POSTS": {"results": []}})
    rows = rows_by_id(run_offer_extraction(posts, provider, today=TODAY, batch_size=2))
    assert all(r["error"] is not None for r in rows.values())


def test_batches_are_capped_at_the_batch_size():
    posts = [post(f"fbpost:{n}", f"${n}00/night") for n in range(1, 6)]
    provider = FakeProvider(responses={"OfferBatch:POSTS": {"results": [
        {"id": p["id"], "price_amount": "100", "price_unit": "night"}
        for p in posts[:2]]}})
    run_offer_extraction(posts[:2], provider, today=TODAY, batch_size=2)
    assert len(provider.calls) == 1


def test_offer_extraction_of_an_empty_list_does_nothing():
    provider = FakeProvider()
    assert run_offer_extraction([], provider, today=TODAY) == []
    assert provider.calls == []


# --- prompt ------------------------------------------------------------------

POSTS = [
    {"id": "fbpost:1", "text": "Room $1400/mo in East Village"},
    {"id": "fbpost:2", "text": "$1800 total for the whole stay, ISO Sep 1"},
]


def test_offer_prompt_states_the_supplied_reference_date():
    prompt = build_offer_prompt(POSTS, today=date(2027, 3, 4))
    assert "Today's date is 2027-03-04" in prompt


def test_offer_prompt_computes_labor_day_for_the_reference_year_not_a_hardcoded_one():
    prompt = build_offer_prompt(POSTS, today=date(2030, 1, 1))
    assert "2026" not in prompt
    assert "Labor Day 2030 is September 2" in prompt


def test_offer_prompt_asks_for_neighborhood_as_written():
    prompt = build_offer_prompt(POSTS, today=TODAY)
    assert "AS WRITTEN" in prompt
    assert "do not normalize" in prompt


def test_offer_prompt_explains_period_pricing_needs_dates():
    prompt = build_offer_prompt(POSTS, today=TODAY)
    assert '"period"' in prompt
    assert "only useful together with dates" in prompt


def test_offer_prompt_embeds_every_post_id_and_text():
    prompt = build_offer_prompt(POSTS, today=TODAY)
    for p in POSTS:
        assert p["id"] in prompt
        assert p["text"] in prompt


def test_offer_prompt_truncates_very_long_posts():
    long_post = [{"id": "fbpost:9", "text": "x" * 5000}]
    prompt = build_offer_prompt(long_post, today=TODAY)
    assert "x" * 1500 in prompt
    assert "x" * 1501 not in prompt


def test_offer_schema_accepts_a_well_formed_batch():
    batch = OfferBatch.model_validate({"results": [
        {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month",
         "currency": "USD", "neighborhood": "East Village", "unit_type": "room",
         "bedrooms": "2", "bath": "shared", "furnished": True,
         "start_date": "2026-08-18", "end_date": "2026-09-08"},
    ]})
    assert batch.results[0].price_unit == "month"


def test_offer_schema_allows_all_fields_null_except_id():
    batch = OfferBatch.model_validate({"results": [{"id": "fbpost:6"}]})
    assert batch.results[0].price_amount is None
    assert batch.results[0].unit_type is None


def test_offer_schema_rejects_an_extraction_shaped_payload():
    """The marker-collision hazard tests/fakes.py documents: the same post id
    sent through extraction then offer shares a bare marker, so an
    ExtractionBatch-shaped canned response could silently satisfy an
    OfferBatch call. It must not: OfferItem should reject the extraction-only
    fields (is_seeking, date_text, budget, confidence) as unknown, not
    quietly default every offer field to null."""
    with pytest.raises(ValidationError):
        OfferBatch.model_validate({"results": [
            {"id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-01",
             "confidence": "high"},
        ]})


# --- nightly_price is computed at write time, once -------------------------

def test_run_offer_extraction_sets_nightly_price_from_amount_unit_and_dates():
    """The wiring gap: the runner must compute `nightly_price` itself, before
    the row ever reaches `OfferRepo.save_many` — otherwise every stored offer
    has a NULL `nightly_price` and `OfferRepo.usable()` is always empty, no
    matter how many priced posts were extracted."""
    provider = FakeProvider(responses={"OfferBatch:fbpost:1": {"results": [
        {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month"},
    ]}})
    rows = run_offer_extraction(
        [post("fbpost:1", "$1400/mo room")], provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    assert row["nightly_price"] == pytest.approx(1400 / 30.4)


def test_run_offer_extraction_sets_nightly_price_for_period_pricing_with_dates():
    provider = FakeProvider(responses={"OfferBatch:fbpost:1": {"results": [
        {"id": "fbpost:1", "price_amount": "1800", "price_unit": "period",
         "start_date": "2026-08-18", "end_date": "2026-09-08"},
    ]}})
    rows = run_offer_extraction(
        [post("fbpost:1", "$1800 total, Aug 18 - Sep 8")], provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    # Aug 18 - Sep 8 is 22 inclusive nights, not 21.
    assert row["nightly_price"] == pytest.approx(1800 / 22)


def test_run_offer_extraction_leaves_nightly_price_null_when_unconvertible():
    """A period price without dates cannot be converted — it must be dropped
    (null nightly_price), never guessed at, and must never crash the run."""
    provider = FakeProvider(responses={"OfferBatch:fbpost:1": {"results": [
        {"id": "fbpost:1", "price_amount": "1800", "price_unit": "period"},
    ]}})
    rows = run_offer_extraction(
        [post("fbpost:1", "$1800 total for the stay")], provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    assert row["nightly_price"] is None


def test_skipped_and_failed_offer_rows_carry_a_null_nightly_price():
    posts = [post("fbpost:1", "no price at all here"),
             post("fbpost:2", "$1400/mo POISON")]
    provider = FakeProvider(fail_on={"POISON"})
    rows = rows_by_id(run_offer_extraction(posts, provider, today=TODAY, batch_size=1))
    assert rows["fbpost:1"]["nightly_price"] is None   # prefiltered
    assert rows["fbpost:2"]["nightly_price"] is None   # failed


def test_a_stored_offer_comes_back_usable_when_its_price_converts(tmp_path):
    """End-to-end proof that closing the wiring gap actually fixes
    `OfferRepo.usable()`: a real extracted-and-saved row for a convertible
    price is returned; one whose price cannot be converted is excluded."""
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    PostRepo(conn).upsert_many([
        {"id": "fbpost:1", "text": "$1400/mo room"},
        {"id": "fbpost:2", "text": "$1800 total for the stay, no dates given"},
    ])
    provider = FakeProvider(responses={
        "OfferBatch:fbpost:1": {"results": [
            {"id": "fbpost:1", "price_amount": "1400", "price_unit": "month"}]},
        "OfferBatch:fbpost:2": {"results": [
            {"id": "fbpost:2", "price_amount": "1800", "price_unit": "period"}]},
    })
    rows = run_offer_extraction(
        [post("fbpost:1", "$1400/mo room"),
         post("fbpost:2", "$1800 total for the stay, no dates given")],
        provider, today=TODAY, batch_size=1)
    OfferRepo(conn).save_many(rows)

    usable_ids = {r["post_id"] for r in OfferRepo(conn).usable()}
    assert usable_ids == {"fbpost:1"}
    assert OfferRepo(conn).by_post_id()["fbpost:2"]["nightly_price"] is None


def test_extraction_shaped_response_cannot_silently_satisfy_an_offer_call():
    """End-to-end version of the collision above, through the real runner and
    FakeProvider: register the response under a BARE marker (as a shared
    provider across passes would produce), shaped like an ExtractionBatch
    result. run_offer_extraction must fail loudly for that post — a recorded
    per-post error — not return a row of silent nulls."""
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-01",
         "confidence": "high"},
    ]}})
    rows = run_offer_extraction(
        [post("fbpost:1", "$1400/mo room in East Village")], provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    assert row["error"] is not None
    assert row["price_amount"] is None
