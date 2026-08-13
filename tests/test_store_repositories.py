from datetime import date, datetime
import pytest
from sublease.profile.models import (
    Constraints, Place, Price, Profile, SourceConfig, Templates, Window,
)
from sublease.store.db import connect, migrate
from sublease.store.repositories import (
    CandidateRepo, EnrichmentRepo, ExtractionRepo, PostRepo, ProfileRepo,
)

NOW = datetime(2026, 8, 11, 9, 0, 0)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    migrate(c)
    return c


def a_profile(**kw):
    base = dict(
        name="East Village room",
        place=Place(neighborhood="East Village"),
        window=Window(start=date(2026, 8, 18), end=date(2026, 9, 8)),
        price=Price(total=2200),
        constraints=Constraints(),
        templates=Templates(outreach_message="Hi {first_name}", listing_post="Room."),
        sources=[SourceConfig(slug="nycsublets", name="NYC Sublets")],
    )
    return Profile(**{**base, **kw})


def a_post(pid="fbpost:1", **kw):
    base = dict(id=pid, source="facebook", url=f"https://fb.com/{pid}",
                group_name="G", author_name="Emma", author_url="https://fb.com/e",
                posted_at="2026-08-09", text="looking for a sublet aug 18 - sep 8")
    return {**base, **kw}


def test_profile_round_trips_with_its_sources(conn):
    saved = ProfileRepo(conn).save(a_profile())
    assert saved.id is not None
    loaded = ProfileRepo(conn).get(saved.id)
    assert loaded == saved
    assert loaded.sources[0].slug == "nycsublets"


def test_saving_an_existing_profile_replaces_its_sources(conn):
    repo = ProfileRepo(conn)
    saved = repo.save(a_profile())
    saved.sources = [SourceConfig(slug="gypsyhousing", name="Ghostlight")]
    repo.save(saved)
    assert [s.slug for s in repo.get(saved.id).sources] == ["gypsyhousing"]


def test_post_upsert_reports_only_new_rows(conn):
    repo = PostRepo(conn)
    assert repo.upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW) == 2
    assert repo.upsert_many([a_post("fbpost:2"), a_post("fbpost:3")], now=NOW) == 1


def test_post_upsert_preserves_the_original_first_seen(conn):
    repo = PostRepo(conn)
    repo.upsert_many([a_post()], now=NOW)
    repo.upsert_many([a_post(text="edited")], now=datetime(2026, 9, 1))
    row = repo.get_many(["fbpost:1"])["fbpost:1"]
    assert row["first_seen"].startswith("2026-08-11")


def test_ids_without_extraction_excludes_extracted_posts(conn):
    PostRepo(conn).upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW)
    ExtractionRepo(conn).save_many([
        {"post_id": "fbpost:1", "is_seeking": True, "start_date": "2026-08-18",
         "end_date": "2026-09-08", "date_text": "aug 18 - sep 8", "budget": None,
         "confidence": "high", "model": "fake", "error": None},
    ], now=NOW)
    assert PostRepo(conn).ids_without_extraction() == ["fbpost:2"]


def test_seeker_ids_returns_only_seekers(conn):
    PostRepo(conn).upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW)
    ExtractionRepo(conn).save_many([
        {"post_id": "fbpost:1", "is_seeking": True, "model": "fake"},
        {"post_id": "fbpost:2", "is_seeking": False, "model": "fake"},
    ], now=NOW)
    assert ExtractionRepo(conn).seeker_ids() == ["fbpost:1"]


def test_enrichment_is_keyed_by_post_id(conn):
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    EnrichmentRepo(conn).save_many([
        {"post_id": "fbpost:1", "people_in_one_room": 1, "wants_multiple_rooms": False,
         "gender": "female", "group_size": 1, "model": "fake"},
    ], now=NOW)
    assert EnrichmentRepo(conn).by_post_id()["fbpost:1"]["gender"] == "female"


def a_candidate(**kw):
    base = dict(person_key="emma|2026-08-18|2026-09-08", post_id="fbpost:1",
                also_posted_in=[], tier="A", tier_reason="covers 22/22 days",
                fit="full-window", days_covered=22, wants_start="2026-08-18",
                wants_end="2026-09-08", draft="Hi Emma")
    return {**base, **kw}


def test_candidate_sync_inserts_then_updates(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    repo = CandidateRepo(conn)
    assert repo.sync(pid, [a_candidate()], now=NOW) == (1, 0)
    assert repo.sync(pid, [a_candidate(tier="B")], now=NOW) == (0, 1)
    assert repo.list(pid)[0]["tier"] == "B"


def test_candidate_sync_never_clobbers_a_human_edited_status(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    repo = CandidateRepo(conn)
    repo.sync(pid, [a_candidate()], now=NOW)
    conn.execute("UPDATE candidate SET status='replied'")
    repo.sync(pid, [a_candidate(tier="C")], now=NOW)
    row = repo.list(pid)[0]
    assert (row["status"], row["tier"]) == ("replied", "C")


def test_candidate_sync_handles_duplicate_person_key_within_one_call(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post()], now=NOW)
    repo = CandidateRepo(conn)
    result = repo.sync(pid, [
        a_candidate(tier="A", tier_reason="first pass"),
        a_candidate(tier="B", tier_reason="second pass"),
    ], now=NOW)
    assert result == (1, 1)
    rows = repo.list(pid)
    assert len(rows) == 1
    assert (rows[0]["tier"], rows[0]["tier_reason"]) == ("B", "second pass")


def test_candidate_list_filters_by_tier(conn):
    pid = ProfileRepo(conn).save(a_profile()).id
    PostRepo(conn).upsert_many([a_post("fbpost:1"), a_post("fbpost:2")], now=NOW)
    CandidateRepo(conn).sync(pid, [
        a_candidate(),
        a_candidate(person_key="ivan|x|y", post_id="fbpost:2", tier="C"),
    ], now=NOW)
    assert [c["tier"] for c in CandidateRepo(conn).list(pid, tier="A")] == ["A"]
