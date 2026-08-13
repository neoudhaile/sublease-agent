import json
from datetime import date
from pathlib import Path
import pytest
from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.fixtures import FixtureSource
from sublease.sources.registry import REGISTERED_METHODS, get_source

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "posts.json"
CFG = SourceConfig(slug="test", name="Fixture Group", method="fixtures")


def test_fixture_source_reads_the_repo_fixtures():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=100)
    assert len(posts) == 10


def test_every_fixture_post_is_normalized():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=100)
    assert {p["id"] for p in posts} == {f"fbpost:{n}" for n in range(1, 11)}
    assert all(p["source"] == "fixtures" for p in posts)
    assert all(p["text"] for p in posts)


def test_fixture_source_uses_each_records_own_group_name():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=100)
    assert {p["group_name"] for p in posts} == {"Fixture Group"}


def test_limit_is_respected():
    posts = FixtureSource(FIXTURES).fetch(CFG, since=date(2026, 8, 1), limit=3)
    assert len(posts) == 3


def test_missing_fixture_file_raises_source_error(tmp_path):
    with pytest.raises(SourceError):
        FixtureSource(tmp_path / "nope.json").fetch(CFG, date(2026, 8, 1), 10)


def test_malformed_fixture_file_raises_source_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SourceError):
        FixtureSource(bad).fetch(CFG, date(2026, 8, 1), 10)


def test_registry_knows_the_three_methods():
    assert REGISTERED_METHODS == {"fixtures", "forage", "apify"}


def test_registry_returns_a_fixture_source():
    assert isinstance(get_source("fixtures", path=FIXTURES), FixtureSource)


def test_registry_rejects_an_unknown_method():
    with pytest.raises(SourceError):
        get_source("carrier-pigeon")


def test_registry_missing_path_raises_source_error():
    """Missing 'path' parameter for fixtures method should raise SourceError, not KeyError."""
    with pytest.raises(SourceError) as exc_info:
        get_source("fixtures")
    assert "path" in str(exc_info.value).lower()


def test_fixture_source_with_list_of_strings_raises_source_error(tmp_path):
    """Fixtures file with list of strings instead of objects should raise SourceError."""
    bad_fixture = tmp_path / "bad_structure.json"
    bad_fixture.write_text('["not", "objects"]')
    with pytest.raises(SourceError) as exc_info:
        FixtureSource(bad_fixture).fetch(CFG, date(2026, 8, 1), 10)
    assert "bad_structure.json" in str(exc_info.value) or "structure" in str(exc_info.value).lower()
