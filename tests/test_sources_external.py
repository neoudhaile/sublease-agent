import json
import subprocess
from datetime import date
from pathlib import Path
import pytest
from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.apify import ApifySource
from sublease.sources.forage import ForageFacebookSource

CFG = SourceConfig(slug="nycsublets", name="NYC Sublets", method="forage")
PAYLOAD = [{"text": "ISO a room Aug 20 - Sep 1",
            "url": "https://facebook.com/groups/nycsublets/posts/42",
            "author": {"name": "Ivan", "url": "/ivan"}, "time": "2026-08-10"}]


def fake_runner_writing(payload, returncode=0, stderr=""):
    def run(cmd, **kwargs):
        out_index = cmd.index("-o") + 1
        Path(cmd[out_index]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(cmd, returncode, "", stderr)
    return run


def test_forage_normalizes_scraped_posts(tmp_path):
    src = ForageFacebookSource(raw_dir=tmp_path, runner=fake_runner_writing(PAYLOAD))
    posts = src.fetch(CFG, since=date(2026, 8, 1), limit=300)
    assert [p["id"] for p in posts] == ["fbpost:42"]
    assert posts[0]["group_name"] == "NYC Sublets"
    assert posts[0]["source"] == "forage"


def test_forage_passes_days_limit_and_delay(tmp_path, monkeypatch):
    # The `--days` value is derived from date.today(), so freeze it here
    # (to the day this test's expectations were authored against) rather
    # than letting the assertion drift with the real wall-clock date.
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 8, 11)

    monkeypatch.setattr("sublease.sources.forage.date", _FixedDate)

    seen = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        Path(cmd[cmd.index("-o") + 1]).write_text("[]")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    ForageFacebookSource(raw_dir=tmp_path, delay=4.5, runner=run).fetch(
        CFG, since=date(2026, 8, 8), limit=150)
    cmd = seen["cmd"]
    assert cmd[1:3] == ["scrape", "nycsublets"]
    assert cmd[cmd.index("--days") + 1] == "3"
    assert cmd[cmd.index("--limit") + 1] == "150"
    assert cmd[cmd.index("--delay") + 1] == "4.5"
    assert "--skip-comments" in cmd and "--no-input" in cmd


def test_forage_raises_source_error_on_nonzero_exit(tmp_path):
    src = ForageFacebookSource(
        raw_dir=tmp_path, runner=fake_runner_writing([], 1, "session expired"))
    with pytest.raises(SourceError, match="session expired"):
        src.fetch(CFG, since=date(2026, 8, 1), limit=10)


def test_forage_raises_source_error_on_unreadable_output(tmp_path):
    def run(cmd, **kwargs):
        Path(cmd[cmd.index("-o") + 1]).write_text("{broken")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(SourceError):
        ForageFacebookSource(raw_dir=tmp_path, runner=run).fetch(
            CFG, since=date(2026, 8, 1), limit=10)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_apify_normalizes_and_sends_the_group_url():
    http = FakeHttp(FakeResponse(PAYLOAD))
    posts = ApifySource(token="tok", http=http).fetch(
        SourceConfig(slug="nycsublets", name="NYC Sublets", method="apify"),
        since=date(2026, 8, 1), limit=50)
    assert [p["id"] for p in posts] == ["fbpost:42"]
    url, kwargs = http.calls[0]
    assert "apify" in url
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    body = kwargs["json"]
    assert body["startUrls"][0]["url"].endswith("/groups/nycsublets")
    assert body["resultsLimit"] == 50


def test_apify_raises_source_error_on_http_failure():
    http = FakeHttp(FakeResponse({}, status=500))
    with pytest.raises(SourceError):
        ApifySource(token="tok", http=http).fetch(CFG, date(2026, 8, 1), 10)


def test_apify_requires_a_token():
    with pytest.raises(SourceError):
        ApifySource(token="", http=FakeHttp(FakeResponse([])))


def test_forage_raises_source_error_on_malformed_structure(tmp_path):
    """Forage output that is valid JSON but structurally wrong raises SourceError."""
    def run(cmd, **kwargs):
        # Write a list of strings instead of list of objects
        Path(cmd[cmd.index("-o") + 1]).write_text(json.dumps(["not", "an", "object"]))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    src = ForageFacebookSource(raw_dir=tmp_path, runner=run)
    with pytest.raises(SourceError, match="malformed forage output"):
        src.fetch(CFG, since=date(2026, 8, 1), limit=10)


def test_apify_raises_source_error_on_malformed_structure():
    """Apify output that is valid JSON but structurally wrong raises SourceError."""
    # Return a dict with 'posts' key containing a list of integers instead of objects
    http = FakeHttp(FakeResponse({"posts": [1, 2, 3]}))
    with pytest.raises(SourceError, match="malformed apify output"):
        ApifySource(token="tok", http=http).fetch(
            CFG, since=date(2026, 8, 1), limit=10)
