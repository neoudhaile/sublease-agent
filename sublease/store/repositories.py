"""Repositories. Each owns one table group and returns plain dicts or Profile objects.

The `sync` on CandidateRepo is add-or-update-but-never-clobber-status: the
prototype learned that lesson when a Notion select-option replace wiped 17
human-set statuses (reference/POSTING_SOP.md, lesson 3).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from sublease.profile.models import Profile, SourceConfig

POST_COLUMNS = ("id", "source", "url", "group_name", "author_name",
                "author_url", "posted_at", "text")
EXTRACTION_COLUMNS = ("post_id", "is_seeking", "start_date", "end_date",
                      "date_text", "budget", "confidence", "model", "error")
ENRICHMENT_COLUMNS = ("post_id", "people_in_one_room", "wants_multiple_rooms",
                      "gender", "group_size", "model")


def _now(now: datetime | None) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


class ProfileRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, profile: Profile) -> Profile:
        row = (
            profile.name,
            profile.place.model_dump_json(),
            profile.window.start.isoformat(),
            profile.window.end.isoformat(),
            int(profile.window.flexible),
            int(profile.window.allow_split),
            profile.window.max_split,
            profile.price.model_dump_json(),
            profile.constraints.model_dump_json(),
            profile.templates.model_dump_json(),
        )
        if profile.id is None:
            cur = self.conn.execute(
                "INSERT INTO profile (name, place, window_start, window_end, flexible,"
                " allow_split, max_split, price, constraints, templates)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            profile.id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE profile SET name=?, place=?, window_start=?, window_end=?,"
                " flexible=?, allow_split=?, max_split=?, price=?, constraints=?,"
                " templates=? WHERE id=?", (*row, profile.id))
        self.conn.execute("DELETE FROM source_config WHERE profile_id=?", (profile.id,))
        self.conn.executemany(
            "INSERT INTO source_config (profile_id, platform, slug, name, method, rules)"
            " VALUES (?,?,?,?,?,?)",
            [(profile.id, s.platform, s.slug, s.name, s.method, json.dumps(s.rules))
             for s in profile.sources])
        return profile

    def get(self, profile_id: int) -> Profile | None:
        row = self.conn.execute("SELECT * FROM profile WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        sources = self.conn.execute(
            "SELECT * FROM source_config WHERE profile_id=? ORDER BY id", (profile_id,)
        ).fetchall()
        return Profile.model_validate({
            "id": row["id"],
            "name": row["name"],
            "place": json.loads(row["place"]),
            "window": {
                "start": row["window_start"], "end": row["window_end"],
                "flexible": bool(row["flexible"]),
                "allow_split": bool(row["allow_split"]),
                "max_split": row["max_split"],
            },
            "price": json.loads(row["price"]),
            "constraints": json.loads(row["constraints"]),
            "templates": json.loads(row["templates"]),
            "sources": [
                SourceConfig(platform=s["platform"], slug=s["slug"], name=s["name"],
                             method=s["method"], rules=json.loads(s["rules"]))
                for s in sources
            ],
        })

    def list(self) -> list[Profile]:
        # `ORDER BY id` is load-bearing: callers (e.g. `sublease doctor`, and
        # `sublease init` when deciding whether a profile already exists)
        # treat `list()[0]` as "the active profile". Do not remove this
        # ordering or make it implementation-defined — the oldest profile
        # (lowest id, i.e. first created) must always sort first.
        ids = [r["id"] for r in self.conn.execute("SELECT id FROM profile ORDER BY id")]
        return [p for p in (self.get(i) for i in ids) if p is not None]


class PostRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_many(self, posts: list[dict], now: datetime | None = None) -> int:
        """Insert new posts, refresh known ones. Returns the count of NEW rows.

        `first_seen` is written only on insert, so a post keeps the timestamp of
        when this tool first saw it however many times it is re-scraped.
        """
        if not posts:
            return 0
        stamp = _now(now)
        ids = [p["id"] for p in posts]
        marks = ",".join("?" * len(ids))
        existing = {
            r["id"] for r in self.conn.execute(
                f"SELECT id FROM post WHERE id IN ({marks})", ids)
        }
        for post in posts:
            values = tuple(post.get(c) for c in POST_COLUMNS)
            self.conn.execute(
                "INSERT INTO post (id, source, url, group_name, author_name,"
                " author_url, posted_at, text, first_seen) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET"
                "   url=excluded.url, group_name=excluded.group_name,"
                "   author_name=excluded.author_name, author_url=excluded.author_url,"
                "   posted_at=excluded.posted_at, text=excluded.text",
                (*values, stamp))
        return len({p["id"] for p in posts} - existing)

    def get_many(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT * FROM post WHERE id IN ({marks})", ids)
        return {r["id"]: dict(r) for r in rows}

    def get_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM post ORDER BY id")]

    def ids_without_extraction(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT p.id FROM post p LEFT JOIN extraction e ON e.post_id = p.id"
            " WHERE e.post_id IS NULL ORDER BY p.id")
        return [r["id"] for r in rows]


class ExtractionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save_many(self, rows: list[dict], now: datetime | None = None) -> None:
        stamp = _now(now)
        self.conn.executemany(
            "INSERT INTO extraction (post_id, is_seeking, start_date, end_date,"
            " date_text, budget, confidence, model, error, extracted_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(post_id) DO NOTHING",
            [(*(r.get(c) for c in EXTRACTION_COLUMNS), stamp) for r in rows])

    def get_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM extraction")]

    def seeker_ids(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT post_id FROM extraction WHERE is_seeking=1 ORDER BY post_id")
        return [r["post_id"] for r in rows]

    def done_ids(self) -> set[str]:
        return {r["post_id"] for r in self.conn.execute("SELECT post_id FROM extraction")}


class EnrichmentRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save_many(self, rows: list[dict], now: datetime | None = None) -> None:
        stamp = _now(now)
        self.conn.executemany(
            "INSERT INTO enrichment (post_id, people_in_one_room, wants_multiple_rooms,"
            " gender, group_size, model, enriched_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(post_id) DO NOTHING",
            [(*(r.get(c) for c in ENRICHMENT_COLUMNS), stamp) for r in rows])

    def by_post_id(self) -> dict[str, dict]:
        return {r["post_id"]: dict(r)
                for r in self.conn.execute("SELECT * FROM enrichment")}

    def done_ids(self) -> set[str]:
        return {r["post_id"] for r in self.conn.execute("SELECT post_id FROM enrichment")}


class CandidateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def sync(self, profile_id: int, candidates: list[dict],
             now: datetime | None = None) -> tuple[int, int]:
        """Add new candidates, refresh derived fields on known ones.

        `status` is never written on update — it belongs to the human.
        """
        stamp = _now(now)
        existing = {
            r["person_key"] for r in self.conn.execute(
                "SELECT person_key FROM candidate WHERE profile_id=?", (profile_id,))
        }
        new = updated = 0
        for c in candidates:
            payload = (c["post_id"], json.dumps(c.get("also_posted_in", [])),
                       c.get("tier"), c.get("tier_reason"), c.get("fit"),
                       c.get("days_covered"), c.get("wants_start"), c.get("wants_end"),
                       c.get("draft"))
            if c["person_key"] in existing:
                self.conn.execute(
                    "UPDATE candidate SET post_id=?, also_posted_in=?, tier=?,"
                    " tier_reason=?, fit=?, days_covered=?, wants_start=?, wants_end=?,"
                    " draft=? WHERE profile_id=? AND person_key=?",
                    (*payload, profile_id, c["person_key"]))
                updated += 1
            else:
                self.conn.execute(
                    "INSERT INTO candidate (profile_id, person_key, post_id,"
                    " also_posted_in, tier, tier_reason, fit, days_covered,"
                    " wants_start, wants_end, draft, first_seen)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (profile_id, c["person_key"], *payload, stamp))
                new += 1
                existing.add(c["person_key"])
        return new, updated

    def list(self, profile_id: int, tier: str | None = None,
             new_only: bool = False) -> list[dict]:
        sql = ["SELECT c.*, p.author_name, p.url AS post_url, p.group_name,"
               " p.author_url, p.text AS post_text FROM candidate c"
               " JOIN post p ON p.id = c.post_id WHERE c.profile_id=?"]
        args: list = [profile_id]
        if tier:
            sql.append("AND c.tier=?")
            args.append(tier)
        if new_only:
            sql.append("AND c.status='new'")
        sql.append("ORDER BY CASE c.tier WHEN 'A' THEN 0 WHEN 'B' THEN 1"
                   " WHEN 'C' THEN 2 ELSE 3 END, c.days_covered DESC")
        rows = self.conn.execute(" ".join(sql), args)
        out = []
        for r in rows:
            d = dict(r)
            d["also_posted_in"] = json.loads(d["also_posted_in"])
            out.append(d)
        return out
