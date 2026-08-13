"""The contract every platform adapter implements."""
from __future__ import annotations

from datetime import date
from typing import Protocol, TypedDict

from sublease.profile.models import SourceConfig


class RawPost(TypedDict):
    id: str
    source: str
    url: str | None
    group_name: str
    author_name: str | None
    author_url: str | None
    posted_at: str | None
    text: str


class Source(Protocol):
    name: str

    def fetch(self, cfg: SourceConfig, since: date, limit: int) -> list[RawPost]:
        """Return posts from one configured source. Raises SourceError on failure."""
        ...
