# tests/test_match_dedupe.py
from datetime import date
from sublease.match.dedupe import dedupe_people, person_key
from sublease.match.types import Candidate

START, END = date(2026, 8, 18), date(2026, 9, 8)


def cand(name, post_id, post_date, group, start=START, end=END):
    return Candidate(
        post_id=post_id, person_key=person_key(name, start, end, post_id=post_id), name=name,
        fit="full-window", days_covered=22, wants_start=start, wants_end=end,
        group_name=group, post_date=post_date)


def test_person_key_is_case_and_whitespace_insensitive():
    assert person_key("  Emma Stone ", START, END) == person_key("emma stone", START, END)


def test_person_key_separates_people_with_different_dates():
    assert person_key("Emma", START, END) != person_key("Emma", START, date(2026, 9, 1))


def test_person_key_handles_a_missing_name():
    assert person_key(None, START, END).startswith("|")


def test_person_key_handles_open_dates():
    assert person_key("Emma", START, None) != person_key("Emma", START, END)


def test_one_person_across_three_groups_collapses_to_one_row():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "Group A"),
        cand("Emma", "fbpost:2", "2026-08-10", "Group B"),
        cand("Emma", "fbpost:3", "2026-08-08", "Group C"),
    ])
    assert len(rows) == 1


def test_dedupe_keeps_the_newest_post():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "Group A"),
        cand("Emma", "fbpost:2", "2026-08-10", "Group B"),
    ])
    assert rows[0].post_id == "fbpost:2"


def test_dedupe_records_the_other_sightings():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "Group A"),
        cand("Emma", "fbpost:2", "2026-08-10", "Group B"),
        cand("Emma", "fbpost:3", "2026-08-08", "Group C"),
    ])
    assert sorted(rows[0].also_posted_in) == ["Group A", "Group C"]


def test_the_same_name_with_different_dates_is_two_people():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "A"),
        cand("Emma", "fbpost:2", "2026-08-10", "B", end=date(2026, 9, 1)),
    ])
    assert len(rows) == 2


def test_different_people_are_never_merged():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "A"),
        cand("Ivan", "fbpost:2", "2026-08-10", "B"),
    ])
    assert len(rows) == 2


def test_dedupe_of_an_empty_list_is_empty():
    assert dedupe_people([]) == []


def test_posts_with_no_date_do_not_crash_the_sort():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", None, "A"),
        cand("Emma", "fbpost:2", "2026-08-10", "B"),
    ])
    assert rows[0].post_id == "fbpost:2"


def test_two_nameless_posts_with_identical_dates_stay_separate():
    rows = dedupe_people([
        cand(None, "fbpost:1", "2026-08-09", "A"),
        cand(None, "fbpost:2", "2026-08-09", "B"),
    ])
    assert len(rows) == 2


def test_nameless_and_named_post_with_identical_dates_do_not_merge():
    rows = dedupe_people([
        cand(None, "fbpost:1", "2026-08-09", "A"),
        cand("Emma", "fbpost:2", "2026-08-09", "B"),
    ])
    assert len(rows) == 2


def test_named_cross_posting_still_merges_keeping_the_newest():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-09", "A"),
        cand("Emma", "fbpost:2", "2026-08-10", "B"),
        cand("Emma", "fbpost:3", "2026-08-08", "C"),
    ])
    assert len(rows) == 1
    assert rows[0].post_id == "fbpost:2"


def test_mixed_post_date_formats_keep_the_genuinely_newest():
    rows = dedupe_people([
        cand("Emma", "fbpost:1", "2026-08-01", "A"),           # ISO date
        cand("Emma", "fbpost:2", "1755000000", "B"),           # unix ts (~Aug 2025)
        cand("Emma", "fbpost:3", "2026-08-10T12:00:00", "C"),  # ISO datetime, newest
        cand("Emma", "fbpost:4", None, "D"),
        cand("Emma", "fbpost:5", "sometime last week", "E"),   # unparseable
    ])
    assert rows[0].post_id == "fbpost:3"


def test_all_unparseable_dates_do_not_raise_and_are_deterministic():
    candidates = [
        cand("Emma", "fbpost:1", "not a date", "A"),
        cand("Emma", "fbpost:2", "also not a date", "B"),
        cand("Emma", "fbpost:3", None, "C"),
    ]
    rows = dedupe_people(candidates)
    first_run = rows[0].post_id
    rows_again = dedupe_people(list(reversed(candidates)))
    assert rows_again[0].post_id == first_run
