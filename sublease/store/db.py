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


def migrate(conn: sqlite3.Connection) -> int:
    """Apply every migration newer than the recorded version. Returns the new version."""
    version = current_version(conn)
    for index, script in enumerate(MIGRATIONS, start=1):
        if index <= version:
            continue
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            raise StoreError(f"migration {index} failed: {exc}") from exc
        version = index
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INT NOT NULL)")
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    return version
