# tests/test_normalize.py
from sublease.sources.normalize import (
    canonical_pid, clean_author_url, load_records, normalize,
)


def test_permalink_and_posts_urls_yield_the_same_id():
    a = canonical_pid("https://facebook.com/groups/x/permalink/12345/", "fb")
    b = canonical_pid("https://facebook.com/groups/y/posts/12345", "fb")
    assert a == b == "fbpost:12345"


def test_story_fbid_query_param_is_recognised():
    assert canonical_pid("https://m.facebook.com/story.php?story_fbid=987&id=1",
                         "fb") == "fbpost:987"


def test_unparseable_url_falls_back():
    assert canonical_pid("https://example.com/thing", "fallback-id") == "fallback-id"


def test_missing_url_falls_back():
    assert canonical_pid(None, "fallback-id") == "fallback-id"


def test_author_url_is_made_absolute_and_stripped_of_tracking():
    assert clean_author_url("/emma?ref=group_x") == "https://www.facebook.com/emma"


def test_author_url_passthrough_for_absolute_urls():
    assert clean_author_url("https://facebook.com/emma") == "https://facebook.com/emma"


def test_author_url_handles_none():
    assert clean_author_url(None) is None


def test_normalize_maps_forage_shape():
    rec = {"text": "ISO a room", "url": "https://facebook.com/groups/g/posts/5",
           "author": {"name": "Emma", "url": "/emma"}, "time": "2026-08-09"}
    post = normalize(rec, "Fixture Group", "facebook")
    assert post["id"] == "fbpost:5"
    assert post["author_name"] == "Emma"
    assert post["author_url"] == "https://www.facebook.com/emma"
    assert post["group_name"] == "Fixture Group"
    assert post["posted_at"] == "2026-08-09"
    assert post["source"] == "facebook"


def test_normalize_maps_apify_shape():
    rec = {"postText": "ISO", "topLevelUrl": "https://facebook.com/groups/g/posts/6",
           "user": {"name": "Ivan", "profileUrl": "https://facebook.com/ivan"},
           "publishedTime": "2026-08-10"}
    post = normalize(rec, "G", "facebook")
    assert (post["id"], post["author_name"]) == ("fbpost:6", "Ivan")


def test_normalize_builds_a_url_from_slug_and_id_when_absent():
    rec = {"text": "ISO", "id": "77", "author": "Solo Author"}
    post = normalize(rec, "G", "facebook", slug="nycsublets")
    assert post["url"] == "https://www.facebook.com/groups/nycsublets/posts/77"
    assert post["id"] == "fbpost:77"


def test_normalize_hashes_when_there_is_no_url_or_id():
    rec = {"text": "ISO a room in august", "author": "Anon"}
    post = normalize(rec, "G", "facebook")
    assert post["id"].startswith("hash:")
    again = normalize(dict(rec), "G", "facebook")
    assert post["id"] == again["id"]


def test_load_records_unwraps_common_envelopes():
    assert load_records([{"a": 1}]) == [{"a": 1}]
    assert load_records({"posts": [{"a": 1}]}) == [{"a": 1}]
    assert load_records({"items": [{"a": 1}]}) == [{"a": 1}]
    assert load_records({"nothing": 1}) == []
