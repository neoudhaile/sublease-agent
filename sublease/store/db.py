"""SQLite connection and forward-only migration."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sublease.errors import StoreError
from sublease.paths import db_path, sublease_home
from sublease.store.schema import MIGRATIONS


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is None:
        sublease_home(create=True)
        path = db_path()
    try:
        conn = sqlite3.connect(path, isolation_level=None)
    except sqlite3.Error as exc:
        raise StoreError(f"cannot open database at {path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    got = conn.execute("SELECT version FROM schema_version").fetchone()
    return got["version"] if got else 0


def _statements(script: str) -> list[str]:
    """Split a migration script into individual statements.

    executescript() can't be used for a migration's DDL: it issues an implicit COMMIT
    before it runs, which would end any explicit transaction before the schema_version
    write could join it. Each migration here is plain DDL with no semicolons inside
    string literals, so splitting on ';' is safe.
    """
    return [s.strip() for s in script.split(";") if s.strip()]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the recorded version. Returns the new version.

    Each migration's DDL and its schema_version bump run inside one explicit
    transaction (BEGIN/COMMIT, ROLLBACK on failure), so a crash or interrupt between
    applying the schema and recording the version can never happen: either both landed
    or neither did, and current_version() can never disagree with what schema is
    actually present.
    """
    version = current_version(conn)
    for index, script in enumerate(MIGRATIONS, start=1):
        if index <= version:
            continue
        try:
            conn.execute("BEGIN")
            for statement in _statements(script):
                conn.execute(statement)
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL)")
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (index,))
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise StoreError(f"migration {index} failed: {exc}") from exc
        version = index
    return version
