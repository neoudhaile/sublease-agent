"""Apify actor adapter for public groups the user has not joined.

Ported from reference/pipeline/scrape.py:119-139.
"""
from __future__ import annotations

from datetime import date

from sublease.errors import SourceError
from sublease.profile.models import SourceConfig
from sublease.sources.base import RawPost
from sublease.sources.normalize import load_records, normalize

ACTOR = "apify~facebook-groups-scraper"
ENDPOINT = (f"https://api.apify.com/v2/acts/{ACTOR}"
            "/run-sync-get-dataset-items?timeout=280&format=json")
TIMEOUT_SECONDS = 300


class ApifySource:
    name = "apify"

    def __init__(self, token: str, http=None) -> None:
        if not token:
            raise SourceError("apify source needs APIFY_TOKEN to be set")
        self.token = token
        if http is None:
            import httpx
            http = httpx.Client(timeout=TIMEOUT_SECONDS)
        self.http = http

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        body = {
            "startUrls": [{"url": f"https://www.facebook.com/groups/{cfg.slug}"}],
            "resultsLimit": limit,
            "viewOption": "CHRONOLOGICAL",
        }
        try:
            response = self.http.post(
                ENDPOINT, json=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.token}"})
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise SourceError(f"apify failed for {cfg.name}: {exc}") from exc

        try:
            return [normalize(rec, cfg.name, self.name, slug=str(cfg.slug))
                    for rec in load_records(payload)]
        except (AttributeError, TypeError) as exc:
            raise SourceError(f"malformed apify output for {cfg.name}: {exc}") from exc
