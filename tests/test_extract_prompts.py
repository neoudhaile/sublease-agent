# tests/test_extract_prompts.py
from datetime import date
import json
from sublease.extract.prompts import build_enrichment_prompt, build_extraction_prompt
from sublease.extract.schemas import ExtractionBatch, EnrichmentBatch

POSTS = [
    {"id": "fbpost:1", "text": "Looking for a sublet Aug 18 to Sep 8"},
    {"id": "fbpost:2", "text": "ISO a room through Labor Day"},
]


def test_extraction_prompt_states_the_supplied_reference_date():
    prompt = build_extraction_prompt(POSTS, today=date(2027, 3, 4))
    assert "Today's date is 2027-03-04" in prompt


def test_extraction_prompt_computes_labor_day_for_the_reference_year():
    assert "Labor Day 2027 is September 6" in build_extraction_prompt(
        POSTS, today=date(2027, 3, 4))


def test_extraction_prompt_does_not_hardcode_the_prototypes_year():
    prompt = build_extraction_prompt(POSTS, today=date(2030, 1, 1))
    assert "2026" not in prompt
    assert "Labor Day 2030 is September 2" in prompt


def test_extraction_prompt_tells_the_model_which_year_to_assume():
    assert "Assume the year 2027" in build_extraction_prompt(POSTS, date(2027, 3, 4))


def test_extraction_prompt_embeds_every_post_id_and_text():
    prompt = build_extraction_prompt(POSTS, today=date(2026, 8, 11))
    for post in POSTS:
        assert post["id"] in prompt
        assert post["text"] in prompt


def test_extraction_prompt_truncates_very_long_posts():
    long_post = [{"id": "fbpost:9", "text": "x" * 5000}]
    prompt = build_extraction_prompt(long_post, today=date(2026, 8, 11))
    assert "x" * 1500 in prompt
    assert "x" * 1501 not in prompt


def test_enrichment_prompt_forbids_guessing_gender_from_a_name():
    prompt = build_enrichment_prompt(POSTS)
    assert "NEVER guess from the person's name" in prompt


def test_enrichment_prompt_keeps_the_two_rooms_distinction():
    prompt = build_enrichment_prompt(POSTS)
    assert "TWO SEPARATE ROOMS" in prompt
    assert "wants_multiple_rooms" in prompt


def test_extraction_schema_accepts_a_well_formed_batch():
    batch = ExtractionBatch.model_validate({"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-18",
         "end_date": "2026-09-08", "date_text": "Aug 18 to Sep 8",
         "budget": "$1800", "confidence": "high"},
    ]})
    assert batch.results[0].is_seeking is True


def test_extraction_schema_allows_null_dates_for_undated_posts():
    batch = ExtractionBatch.model_validate({"results": [
        {"id": "fbpost:6", "is_seeking": False, "start_date": None,
         "end_date": None, "date_text": None, "budget": None, "confidence": "low"},
    ]})
    assert batch.results[0].start_date is None


def test_enrichment_schema_accepts_a_well_formed_batch():
    batch = EnrichmentBatch.model_validate({"results": [
        {"id": "fbpost:1", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": "female", "group_size": 1},
    ]})
    assert batch.results[0].gender == "female"


def test_enrichment_schema_allows_unknown_gender():
    batch = EnrichmentBatch.model_validate({"results": [
        {"id": "fbpost:1", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": None, "group_size": 1},
    ]})
    assert batch.results[0].gender is None
