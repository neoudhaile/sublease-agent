import sqlite3
import pytest
from sublease.store.db import connect, current_version, migrate
from sublease.store.schema import MIGRATIONS

TABLES = {
    "profile", "source_config", "post", "extraction", "enrichment",
    "candidate", "outreach_action", "my_post", "schema_version",
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_migrate_creates_every_table(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    assert TABLES <= table_names(conn)


def test_migrate_records_the_version(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    assert current_version(conn) == len(MIGRATIONS)


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    conn = connect(path)
    migrate(conn)
    migrate(conn)
    assert current_version(conn) == len(MIGRATIONS)


def test_wal_mode_is_enabled(tmp_path):
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_foreign_keys_are_enforced(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO candidate (profile_id, person_key, post_id, first_seen) "
            "VALUES (999, 'nobody', 'fbpost:1', '2026-08-11')"
        )


def test_rows_come_back_keyed_by_column_name(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == len(MIGRATIONS)


def test_candidate_person_key_is_unique_per_profile(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO profile (id, name, place, window_start, window_end, price, "
        "constraints, templates) VALUES (1,'p','{}','2026-08-18','2026-09-08','{}','{}','{}')"
    )
    conn.execute(
        "INSERT INTO post (id, text, first_seen) VALUES ('fbpost:1','hi','2026-08-11')"
    )
    args = (1, "emma|2026-08-18|2026-09-08", "fbpost:1", "2026-08-11")
    sql = ("INSERT INTO candidate (profile_id, person_key, post_id, first_seen) "
           "VALUES (?,?,?,?)")
    conn.execute(sql, args)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, args)
