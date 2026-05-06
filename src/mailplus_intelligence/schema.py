"""Metadata schema bootstrap for the structured recall layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


_MIGRATIONS = [
    "001_metadata_schema_v0.sql",
    "002_attachment_metadata.sql",
    "003_cache_and_queue.sql",
]


def apply_schema_v0(connection: sqlite3.Connection) -> None:
    """Apply the v0 metadata schema to an open SQLite connection."""

    migration_path = MIGRATIONS_DIR / "001_metadata_schema_v0.sql"
    connection.executescript(migration_path.read_text(encoding="utf-8"))


def apply_all_migrations(connection: sqlite3.Connection) -> None:
    """Apply all schema migrations in order. Skips migrations already applied."""

    current_version = current_schema_version(connection)
    for index, filename in enumerate(_MIGRATIONS):
        target_version = index + 1
        if current_version >= target_version:
            continue
        connection.executescript((MIGRATIONS_DIR / filename).read_text(encoding="utf-8"))
        current_version = target_version


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the SQLite user_version after migrations run."""

    return int(connection.execute("PRAGMA user_version").fetchone()[0])
