"""Turn each scraper's idiosyncratic record shape into one RawPost.

Ported from reference/pipeline/scrape.py:22-88. The canonical id matters:
two scrapers seeing the same Facebook post must produce the same string, or the
same person shows up twice (prototype lesson 7).

`canonical_pid` recognises three post-id shapes wherever they appear (after
`permalink/` or `posts/`, or in a `story_fbid=` query param): plain numeric
ids (`12345`), composite `<actor_id>_<post_id>` ids (`100012345_998877`,
captured in full so two different posts by the same actor don't collide),
and Facebook's current opaque `pfbid...` permalink tokens (already globally
unique, used as-is). The URL-building fallback path in `normalize` and the
direct id-fallback path are kept in agreement so the same record yields the
same id whether or not `slug` is supplied.

`clean_author_url` strips Facebook's tracking query params (`ref`, `fbclid`,
`__cft__[0]`, etc.) but keeps `id`, since `profile.php?id=...` is the
canonical profile URL for any user without a vanity username - stripping it
would collapse every such person onto the identical dead link
`profile.php`.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode

from sublease.sources.base import RawPost

_FB_POST_TOKEN = r"pfbid[A-Za-z0-9]+|\d+(?:_\d+)?"
FB_POST_ID = re.compile(
    rf"(?:permalink|posts)/({_FB_POST_TOKEN})|story_fbid=({_FB_POST_TOKEN})")

_TEXT_KEYS = ("text", "post_text", "content", "message", "postText")
_URL_KEYS = ("url", "post_url", "postUrl", "link", "topLevelUrl", "facebookUrl")
_AUTHOR_NAME_KEYS = ("name", "username", "title")
_AUTHOR_URL_KEYS = ("url", "profileUrl", "profile_url", "link")
_TIME_KEYS = ("time", "date", "timestamp", "posted_at", "creation_time",
              "date_posted", "publishedTime")

# Query params that carry author identity rather than tracking noise.
# `profile.php?id=...` is Facebook's canonical URL for users without a
# vanity username; everything else (`ref`, `fbclid`, `__cft__[0]`, ...) is
# tracking junk and gets dropped.
_AUTHOR_URL_KEEP_PARAMS = {"id"}


def _first(rec: dict, *keys):
    for key in keys:
        value = rec.get(key)
        if value:
            return value
    return None


def clean_author_url(url: str | None) -> str | None:
    if not url:
        return url
    path, sep, query = url.partition("?")
    if sep:
        kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                if k in _AUTHOR_URL_KEEP_PARAMS]
        path = path + ("?" + urlencode(kept) if kept else "")
    if path.startswith("/"):
        path = "https://www.facebook.com" + path
    return path


def canonical_pid(url: str | None, fallback: str) -> str:
    if url:
        match = FB_POST_ID.search(url)
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
