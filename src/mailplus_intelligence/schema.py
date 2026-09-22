"""Metadata schema bootstrap for the structured recall layer."""

from __future__ import annotations

from importlib import resources
import sqlite3


_MIGRATIONS = [
    "001_metadata_schema_v0.sql",
    "002_attachment_metadata.sql",
    "003_cache_and_queue.sql",
    "004_semantic_provenance_review.sql",
    "005_cache_privacy.sql",
    "006_ingest_decisions.sql",
]


def _read_migration(filename: str) -> str:
    """Read a migration from the installed package resource tree."""

    migration = resources.files("mailplus_intelligence").joinpath("migrations", filename)
    try:
        return migration.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"required migration package resource is missing: migrations/{filename}"
        ) from exc


def apply_schema_v0(connection: sqlite3.Connection) -> None:
    """Apply the v0 metadata schema to an open SQLite connection."""

    connection.executescript(_read_migration("001_metadata_schema_v0.sql"))


def apply_all_migrations(connection: sqlite3.Connection) -> None:
    """Apply all schema migrations in order. Skips migrations already applied."""

    current_version = current_schema_version(connection)
    for index, filename in enumerate(_MIGRATIONS):
        target_version = index + 1
        if current_version >= target_version:
            continue
        connection.executescript(_read_migration(filename))
        current_version = target_version


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the SQLite user_version after migrations run."""

    return int(connection.execute("PRAGMA user_version").fetchone()[0])
