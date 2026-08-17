import sqlite3
import pytest
from sublease.store.db import connect, current_version, migrate
from sublease.store.schema import MIGRATIONS, _V1

TABLES = {
    "profile", "source_config", "post", "extraction", "enrichment",
    "candidate", "outreach_action", "my_post", "offer", "schema_version",
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


def test_existing_v1_database_migrates_forward_without_data_loss(tmp_path):
    """Pins that a database created before the `offer` migration existed gains the
    new table and keeps its old data when migrated forward. A fresh-database test
    alone would not catch a migration that only works starting from nothing.
    """
    path = tmp_path / "t.db"
    conn = connect(path)
    # Build a database at exactly the old (v1-only) schema, by hand, the way a
    # real installed copy would look before this migration shipped.
    conn.executescript(_V1)
    conn.execute("CREATE TABLE schema_version (version INT NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.execute(
        "INSERT INTO post (id, text, first_seen) VALUES ('fbpost:1','hi','2026-08-11')"
    )
    assert current_version(conn) == 1
    assert "offer" not in table_names(conn)

    migrate(conn)

    assert current_version(conn) == len(MIGRATIONS)
    assert "offer" in table_names(conn)
    row = conn.execute("SELECT text FROM post WHERE id='fbpost:1'").fetchone()
    assert row["text"] == "hi"


def test_offer_post_id_cascades_on_post_delete(tmp_path):
    conn = connect(tmp_path / "t.db")
    migrate(conn)
    conn.execute("INSERT INTO post (id, text, first_seen) VALUES ('fbpost:1','hi','2026-08-11')")
    conn.execute(
        "INSERT INTO offer (post_id, extracted_at) VALUES ('fbpost:1', '2026-08-11')"
    )
    conn.execute("DELETE FROM post WHERE id='fbpost:1'")
    assert conn.execute("SELECT * FROM offer").fetchall() == []


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


class _FlakyConnection:
    """Wraps a real connection and raises once a chosen statement is executed.

    sqlite3.Connection is an immutable C type, so its `execute` method can't be
    monkeypatched directly. This proxy delegates everything to the real connection
    except one `.execute()` call, which it intercepts to simulate a crash or
    interrupt partway through `migrate()`.
    """

    def __init__(self, real, trigger):
        self._real = real
        self._trigger = trigger

    def execute(self, sql, *args, **kwargs):
        if self._trigger in sql:
            raise sqlite3.OperationalError("simulated interrupt")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_migrate_never_records_a_version_whose_schema_was_not_applied(tmp_path):
    """Pins the atomicity of migrate(): a failure between applying a migration's
    DDL and recording its version must leave neither in effect.

    This forces the INSERT into schema_version to raise, simulating a crash or
    interrupt right where the old DELETE-then-INSERT implementation had a window
    between two separate autocommit statements. Against that old implementation
    the migration's CREATE TABLE statements (run via executescript, which commits
    immediately) survive the forced failure while the version write does not, so
    current_version() reports 0 even though the schema tables already exist —
    this test's second assertion catches exactly that mismatch and fails against
    the old implementation. Against the fixed implementation, the whole migration
    (DDL + version write) is one transaction, so the forced failure rolls
    everything back and both assertions hold.
    """
    path = tmp_path / "t.db"
    real_conn = connect(path)
    flaky = _FlakyConnection(real_conn, "INSERT INTO schema_version")

    with pytest.raises(Exception):
        migrate(flaky)

    assert current_version(real_conn) == 0
    assert "profile" not in table_names(real_conn)
