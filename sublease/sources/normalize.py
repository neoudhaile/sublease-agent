"""Turn each scraper's idiosyncratic record shape into one RawPost.

Ported from reference/pipeline/scrape.py:22-88. The canonical id matters:
two scrapers seeing the same Facebook post must produce the same string, or the
same person shows up twice (prototype lesson 7).
"""
from __future__ import annotations

import hashlib
import re

from sublease.sources.base import RawPost

FB_POST_NUM = re.compile(r"(?:permalink|posts)/(\d+)|story_fbid=(\d+)")

_TEXT_KEYS = ("text", "post_text", "content", "message", "postText")
_URL_KEYS = ("url", "post_url", "postUrl", "link", "topLevelUrl", "facebookUrl")
_AUTHOR_NAME_KEYS = ("name", "username", "title")
_AUTHOR_URL_KEYS = ("url", "profileUrl", "profile_url", "link")
_TIME_KEYS = ("time", "date", "timestamp", "posted_at", "creation_time",
              "date_posted", "publishedTime")


def _first(rec: dict, *keys):
    for key in keys:
        value = rec.get(key)
        if value:
            return value
    return None


def clean_author_url(url: str | None) -> str | None:
    if not url:
        return url
    url = url.split("?")[0]
    if url.startswith("/"):
        url = "https://www.facebook.com" + url
    return url


def canonical_pid(url: str | None, fallback: str) -> str:
    if url:
        match = FB_POST_NUM.search(url)
        if match:
            return f"fbpost:{match.group(1) or match.group(2)}"
    return fallback


def load_records(payload) -> list[dict]:
    """Scraper output is sometimes a bare list, sometimes wrapped."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("posts", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def normalize(rec: dict, group_name: str, source: str,
              slug: str | None = None) -> RawPost:
    text = _first(rec, *_TEXT_KEYS) or ""
    url = _first(rec, *_URL_KEYS)
    if not url and slug and rec.get("id"):
        url = f"https://www.facebook.com/groups/{slug}/posts/{rec['id']}"

    author = rec.get("author") or rec.get("user") or {}
    if isinstance(author, dict):
        author_name = _first(author, *_AUTHOR_NAME_KEYS)
        author_url = _first(author, *_AUTHOR_URL_KEYS)
    else:
        author_name, author_url = str(author), None
    author_name = author_name or _first(rec, "author_name", "username", "userName")
    author_url = clean_author_url(
        author_url or _first(rec, "author_url", "profile_url", "userUrl"))

    posted = _first(rec, *_TIME_KEYS)
    digest = hashlib.sha1(
        f"{group_name}|{author_name}|{text[:200]}".encode()).hexdigest()
    fallback = f"fbpost:{rec['id']}" if rec.get("id") else f"hash:{digest}"

    return RawPost(
        id=canonical_pid(url, fallback),
        source=source,
        url=url,
        group_name=group_name,
        author_name=author_name,
        author_url=author_url,
        posted_at=str(posted) if posted else None,
        text=text,
    )
