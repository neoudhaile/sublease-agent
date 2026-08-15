# tests/test_match_dedupe.py
from datetime import date
from sublease.match.dedupe import dedupe_people, person_key
from sublease.match.types import Candidate

START, END = date(2026, 8, 18), date(2026, 9, 8)


def cand(name, post_id, post_date, group, start=START, end=END):
    return Candidate(
        post_id=post_id, person_key=person_key(name, start, end), name=name,
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
