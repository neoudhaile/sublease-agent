import csv
import io
from datetime import date
from sublease.cli.report import candidates_table, coverage_lines, rows_to_csv
from sublease.match.coverage import coverage
from sublease.match.types import Candidate

ROWS = [
    {"tier": "A", "tier_reason": "covers 22/22 days", "author_name": "Emma Stone",
     "days_covered": 22, "fit": "full-window", "wants_start": "2026-08-18",
     "wants_end": "2026-09-08", "group_name": "NYC Sublets", "status": "new",
     "post_url": "https://fb.com/1", "author_url": "https://fb.com/emma",
     "draft": "Hi Emma", "post_text": "ISO a room", "also_posted_in": ["Group B"]},
    {"tier": "C", "tier_reason": "covers only 10/22 days", "author_name": "Nia",
     "days_covered": 10, "fit": "inside", "wants_start": "2026-08-30",
     "wants_end": "2026-09-08", "group_name": "NYU Housing", "status": "new",
     "post_url": "https://fb.com/2", "author_url": "https://fb.com/nia",
     "draft": "Hi Nia", "post_text": "ISO", "also_posted_in": []},
]


def test_table_has_one_row_per_candidate():
    assert candidates_table(ROWS).row_count == 2


def test_table_shows_tier_name_and_coverage():
    headers = [c.header for c in candidates_table(ROWS).columns]
    assert "tier" in headers and "name" in headers and "days" in headers


def test_empty_rows_still_produce_a_table():
    assert candidates_table([]).row_count == 0


def test_csv_round_trips_every_row():
    parsed = list(csv.DictReader(io.StringIO(rows_to_csv(ROWS))))
    assert len(parsed) == 2
    assert parsed[0]["author_name"] == "Emma Stone"


def test_csv_includes_the_draft_message():
    assert "draft" in csv.DictReader(io.StringIO(rows_to_csv(ROWS))).fieldnames


def test_csv_flattens_the_cross_posted_group_list():
    parsed = list(csv.DictReader(io.StringIO(rows_to_csv(ROWS))))
    assert parsed[0]["also_posted_in"] == "Group B"


def test_csv_of_no_rows_is_just_a_header():
    assert len(rows_to_csv([]).strip().splitlines()) == 1


def cand(name, start, end):
    return Candidate(post_id=f"p:{name}", person_key=name, name=name,
                     fit="inside", days_covered=(end - start).days + 1,
                     wants_start=start, wants_end=end)


def test_coverage_lines_report_a_complete_single():
    plan = coverage([cand("Emma", date(2026, 8, 18), date(2026, 9, 8))],
                    date(2026, 8, 18), date(2026, 9, 8))
    text = "\n".join(coverage_lines(plan))
    assert "Emma" in text and "22/22" in text


def test_coverage_lines_report_a_combination():
    plan = coverage(
        [cand("Fiona", date(2026, 8, 18), date(2026, 8, 31)),
         cand("Nia", date(2026, 8, 31), date(2026, 9, 8))],
        date(2026, 8, 18), date(2026, 9, 8), max_split=3)
    text = "\n".join(coverage_lines(plan))
    assert "Fiona" in text and "Nia" in text
    assert "2 people" in text


def test_coverage_lines_say_so_when_nothing_covers_the_window():
    plan = coverage([], date(2026, 8, 18), date(2026, 9, 8))
    assert "No candidates" in "\n".join(coverage_lines(plan))
