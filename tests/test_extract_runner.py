from datetime import date
from sublease.extract.runner import parse_iso_date, run_enrichment, run_extraction
from tests.fakes import FakeProvider

TODAY = date(2026, 8, 11)


def post(pid, text):
    return {"id": pid, "text": text}


def rows_by_id(rows):
    return {r["post_id"]: r for r in rows}


def test_posts_with_no_date_token_never_reach_the_model():
    provider = FakeProvider()
    rows = run_extraction([post("fbpost:6", "Anyone know a good mover? Thanks!")],
                          provider, today=TODAY)
    assert provider.calls == []
    row = rows_by_id(rows)["fbpost:6"]
    assert row["is_seeking"] is False
    assert row["error"] is None


def test_dated_posts_are_extracted_and_shaped_for_the_repository():
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-18",
         "end_date": "2026-09-08", "date_text": "Aug 18 to Sep 8",
         "budget": "$1800", "confidence": "high"},
    ]}})
    rows = run_extraction([post("fbpost:1", "sublet Aug 18 to Sep 8")],
                          provider, today=TODAY)
    row = rows_by_id(rows)["fbpost:1"]
    assert row["is_seeking"] is True
    assert row["start_date"] == "2026-08-18"
    assert row["model"] == "fake-model"


def test_batches_are_capped_at_the_batch_size():
    posts = [post(f"fbpost:{n}", "sublet in august") for n in range(1, 6)]
    provider = FakeProvider(responses={"POSTS": {"results": [
        {"id": p["id"], "is_seeking": True} for p in posts[:2]]}})
    run_extraction(posts[:2], provider, today=TODAY, batch_size=2)
    assert len(provider.calls) == 1


def test_a_failing_batch_bisects_down_to_the_offending_post():
    good = post("fbpost:1", "sublet in august")
    bad = post("fbpost:2", "sublet in august POISON")
    provider = FakeProvider(
        responses={"fbpost:1": {"results": [{"id": "fbpost:1", "is_seeking": True}]}},
        fail_on={"POISON"},
    )
    rows = rows_by_id(run_extraction([good, bad], provider, today=TODAY, batch_size=2))
    assert rows["fbpost:1"]["is_seeking"] is True
    assert rows["fbpost:2"]["is_seeking"] is False
    assert "fake failure" in rows["fbpost:2"]["error"]


def test_every_post_gets_exactly_one_row_even_when_some_fail():
    posts = [post("fbpost:1", "august"), post("fbpost:2", "august POISON"),
             post("fbpost:3", "no timeframe here")]
    provider = FakeProvider(
        responses={"fbpost:1": {"results": [{"id": "fbpost:1", "is_seeking": True}]}},
        fail_on={"POISON"})
    rows = run_extraction(posts, provider, today=TODAY, batch_size=1)
    assert sorted(r["post_id"] for r in rows) == ["fbpost:1", "fbpost:2", "fbpost:3"]


def test_a_short_model_response_is_treated_as_a_batch_failure():
    posts = [post("fbpost:1", "august"), post("fbpost:2", "august")]
    # Empty results are short relative to ANY batch size, so the mismatch survives
    # bisection down to the single-post base case instead of accidentally satisfying
    # a size-1 sub-batch's length check once bisected (see task-12-report.md).
    provider = FakeProvider(responses={"POSTS": {"results": []}})
    rows = rows_by_id(run_extraction(posts, provider, today=TODAY, batch_size=2))
    assert all(r["error"] is not None for r in rows.values())


def test_unparseable_dates_become_null_rather_than_raising():
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "is_seeking": True, "start_date": "next Tuesday"}]}})
    rows = rows_by_id(run_extraction([post("fbpost:1", "august")], provider, TODAY))
    assert rows["fbpost:1"]["start_date"] is None


def test_parse_iso_date_accepts_valid_and_rejects_junk():
    assert parse_iso_date("2026-08-18") == "2026-08-18"
    assert parse_iso_date("2026-08-18T00:00:00") == "2026-08-18"
    assert parse_iso_date("soon") is None
    assert parse_iso_date(None) is None


def test_enrichment_shapes_rows_for_the_repository():
    provider = FakeProvider(responses={"fbpost:1": {"results": [
        {"id": "fbpost:1", "people_in_one_room": 2, "wants_multiple_rooms": False,
         "gender": "male", "group_size": 2}]}})
    rows = rows_by_id(run_enrichment([post("fbpost:1", "me and my partner")], provider))
    assert rows["fbpost:1"]["people_in_one_room"] == 2
    assert rows["fbpost:1"]["gender"] == "male"


def test_enrichment_failure_falls_back_to_a_safe_solo_default():
    provider = FakeProvider(fail_on={"POISON"})
    rows = rows_by_id(run_enrichment([post("fbpost:2", "POISON")], provider))
    assert rows["fbpost:2"]["people_in_one_room"] == 1
    assert rows["fbpost:2"]["gender"] is None


def test_enrichment_of_an_empty_list_does_nothing():
    provider = FakeProvider()
    assert run_enrichment([], provider) == []
    assert provider.calls == []


def test_extraction_with_duplicated_and_missing_ids_is_treated_as_failure():
    """Batch with right count but one id duplicated and one missing."""
    posts = [post("fbpost:1", "august"), post("fbpost:2", "august"),
             post("fbpost:3", "august")]
    # Returns 3 results (correct count) but fbpost:1 is duplicated and fbpost:3 is missing
    provider = FakeProvider(responses={"POSTS": {"results": [
        {"id": "fbpost:1", "is_seeking": True},
        {"id": "fbpost:1", "is_seeking": True},
        {"id": "fbpost:2", "is_seeking": True},
    ]}})
    rows = rows_by_id(run_extraction(posts, provider, today=TODAY, batch_size=3))
    # Every post should get exactly one row
    assert sorted(rows.keys()) == ["fbpost:1", "fbpost:2", "fbpost:3"]
    # The posts with mismatched IDs should have errors
    assert rows["fbpost:1"]["error"] is not None
    assert rows["fbpost:2"]["error"] is not None
    assert rows["fbpost:3"]["error"] is not None


def test_enrichment_with_duplicated_and_missing_ids_is_treated_as_failure():
    """Batch with right count but one id duplicated and one missing."""
    posts = [post("fbpost:1", "me and my partner"), post("fbpost:2", "solo"),
             post("fbpost:3", "with friends")]
    # Returns 3 results (correct count) but fbpost:1 is duplicated and fbpost:3 is missing
    provider = FakeProvider(responses={"POSTS": {"results": [
        {"id": "fbpost:1", "people_in_one_room": 2, "wants_multiple_rooms": False,
         "gender": "male", "group_size": 2},
        {"id": "fbpost:1", "people_in_one_room": 2, "wants_multiple_rooms": False,
         "gender": "male", "group_size": 2},
        {"id": "fbpost:2", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": None, "group_size": 1},
    ]}})
    rows = rows_by_id(run_enrichment(posts, provider, batch_size=3))
    # Every post should get exactly one row
    assert sorted(rows.keys()) == ["fbpost:1", "fbpost:2", "fbpost:3"]
    # All posts should be in the result
    assert len(rows) == 3


def test_extraction_with_unknown_id_is_treated_as_failure():
    """Response contains an id that was never sent."""
    posts = [post("fbpost:1", "august"), post("fbpost:2", "august")]
    # Returns an id that was never sent
    provider = FakeProvider(responses={"POSTS": {"results": [
        {"id": "fbpost:1", "is_seeking": True},
        {"id": "fbpost:999", "is_seeking": True},
    ]}})
    rows = rows_by_id(run_extraction(posts, provider, today=TODAY, batch_size=2))
    # Every sent post should get exactly one row
    assert sorted(rows.keys()) == ["fbpost:1", "fbpost:2"]
    # Both should have errors because IDs don't match
    assert rows["fbpost:1"]["error"] is not None
    assert rows["fbpost:2"]["error"] is not None
    # The unknown ID should not appear in results
    assert "fbpost:999" not in rows
