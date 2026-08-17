# tests/test_match_ranking.py
from datetime import date
from sublease.match.ranking import rank, to_rows
from sublease.profile.models import (
    Constraints, Place, Price, Profile, Templates, Window,
)


def a_profile(**kw):
    base = dict(
        name="East Village room",
        place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(
            outreach_message="Hi {first_name}, saw your post in {group} for {their_dates}",
            listing_post="Room available."),
    )
    return Profile(**{**base, **kw})


def post(pid, name, group="NYC Sublets", posted="2026-08-10", text="ISO a room"):
    return {"id": pid, "author_name": name, "author_url": f"https://fb.com/{name}",
            "url": f"https://fb.com/{pid}", "group_name": group,
            "posted_at": posted, "text": text}


def extraction(pid, seeking=True, start="2026-08-18", end="2026-09-08", **kw):
    base = {"post_id": pid, "is_seeking": seeking, "start_date": start,
            "end_date": end, "budget": None, "confidence": "high",
            "date_text": None}
    return {**base, **kw}


def enrichment(pid, **kw):
    base = {"post_id": pid, "people_in_one_room": 1, "wants_multiple_rooms": False,
            "gender": None, "group_size": 1}
    return {**base, **kw}


def test_offerers_are_excluded():
    got = rank({"p1": post("p1", "Olga")}, [extraction("p1", seeking=False)], {},
               a_profile())
    assert got == []


def test_candidates_outside_the_window_are_excluded():
    posts = {"p1": post("p1", "Otis")}
    ext = [extraction("p1", start="2026-09-15", end="2026-10-30")]
    assert rank(posts, ext, {}, a_profile()) == []


def test_extractions_with_no_matching_post_are_skipped():
    assert rank({}, [extraction("ghost")], {}, a_profile()) == []


def test_a_matching_seeker_becomes_a_tiered_candidate():
    got = rank({"p1": post("p1", "Emma Stone")}, [extraction("p1")],
               {"p1": enrichment("p1")}, a_profile())
    assert len(got) == 1
    assert got[0].name == "Emma Stone"
    assert got[0].tier == "A"
    assert got[0].fit == "full-window"
    assert got[0].days_covered == 22


def test_the_draft_is_rendered_from_the_profile_template():
    got = rank({"p1": post("p1", "Emma Stone")}, [extraction("p1")], {}, a_profile())
    assert got[0].draft == (
        "Hi Emma, saw your post in NYC Sublets for Aug 18 – Sep 8")


def test_missing_enrichment_defaults_to_a_solo_occupant():
    got = rank({"p1": post("p1", "Emma")}, [extraction("p1")], {}, a_profile())
    assert got[0].people_in_one_room == 1
    assert got[0].tier == "A"


def test_enrichment_drives_the_dealbreaker_tier():
    got = rank({"p1": post("p1", "Owen")}, [extraction("p1")],
               {"p1": enrichment("p1", people_in_one_room=2)}, a_profile())
    assert got[0].tier == "D"


def test_gender_preference_is_applied_from_the_profile():
    profile = a_profile(constraints=Constraints(gender_preference="male"))
    got = rank({"p1": post("p1", "Emma")}, [extraction("p1")],
               {"p1": enrichment("p1", gender="female")}, profile)
    assert got[0].tier == "B"


def test_cross_posted_people_collapse_to_one_candidate():
    posts = {"p1": post("p1", "Emma", group="Group A", posted="2026-08-09"),
             "p2": post("p2", "Emma", group="Group B", posted="2026-08-10")}
    got = rank(posts, [extraction("p1"), extraction("p2")], {}, a_profile())
    assert len(got) == 1
    assert got[0].post_id == "p2"
    assert got[0].also_posted_in == ["Group A"]


def test_results_are_ordered_by_tier_then_days_covered():
    posts = {"p1": post("p1", "Partial"), "p2": post("p2", "Full"),
             "p3": post("p3", "Couple")}
    ext = [extraction("p1", start="2026-08-20", end="2026-09-01"),
           extraction("p2"),
           extraction("p3")]
    enr = {"p3": enrichment("p3", people_in_one_room=2)}
    got = rank(posts, ext, enr, a_profile())
    assert [c.name for c in got] == ["Full", "Partial", "Couple"]


def test_ties_are_broken_by_recency():
    posts = {"p1": post("p1", "Older", posted="2026-08-05"),
             "p2": post("p2", "Newer", posted="2026-08-11")}
    got = rank(posts, [extraction("p1"), extraction("p2")], {}, a_profile())
    assert [c.name for c in got] == ["Newer", "Older"]


def test_post_text_is_carried_and_truncated():
    long_text = "x" * 900
    got = rank({"p1": post("p1", "Emma", text=long_text)}, [extraction("p1")], {},
               a_profile())
    assert len(got[0].post_text) == 500


def test_newlines_are_flattened_in_carried_post_text():
    got = rank({"p1": post("p1", "Emma", text="line one\nline two")},
               [extraction("p1")], {}, a_profile())
    assert "\n" not in got[0].post_text


def test_to_rows_shapes_candidates_for_the_repository():
    got = rank({"p1": post("p1", "Emma")}, [extraction("p1")], {}, a_profile())
    row = to_rows(got)[0]
    assert row["person_key"] == got[0].person_key
    assert row["post_id"] == "p1"
    assert row["tier"] == "A"
    assert row["wants_start"] == "2026-08-18"
    assert row["also_posted_in"] == []


def test_to_rows_serialises_open_dates_as_none():
    got = rank({"p1": post("p1", "Omar")},
               [extraction("p1", start="2026-08-22", end=None)], {}, a_profile())
    row = to_rows(got)[0]
    assert row["wants_end"] is None


# --- Fix wave 2026-08-15 ----------------------------------------------------
# Finding 1: ranking used to break recency ties with a raw string comparison
# on `post_date`, the same bug class dedupe.py was fixed for. A unix
# timestamp string and an ISO date string compare backwards as raw strings
# (any "17xxxxxxxx" timestamp sorts below any "20xx-xx-xx" ISO date purely
# because '1' < '2'), regardless of which post is actually newer.

def test_recency_tie_break_understands_mixed_date_formats():
    # p1 is genuinely the newer post (2026-08-20) but stored as a unix
    # timestamp; p2 is genuinely older (2026-01-01) but stored as an ISO
    # date. A raw string sort would rank p2 "newer" since "2026-01-01" >
    # "1787184000" lexicographically. The date-aware key must not.
    posts = {"p1": post("p1", "Newer", posted="1787184000"),
             "p2": post("p2", "Older", posted="2026-01-01")}
    got = rank(posts, [extraction("p1"), extraction("p2")], {}, a_profile())
    assert [c.name for c in got] == ["Newer", "Older"]
