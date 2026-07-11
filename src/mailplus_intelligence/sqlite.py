"""SQLite connection helpers for local metadata/index foundations."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def _create_owner_only_database_file(database: Path) -> None:
    if database.exists():
        return

    try:
        file_descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return

    os.close(file_descriptor)


def connect_sqlite(database: str | Path = ":memory:") -> sqlite3.Connection:
    """Open a SQLite connection with project defaults for index work."""

    database_name = str(database)
    if database_name != ":memory:":
        _create_owner_only_database_file(Path(database))

    connection = sqlite3.connect(database_name)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    if database_name != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
        enforce_owner_only_database_files(connection)

    return connection


def enforce_owner_only_database_files(connection: sqlite3.Connection) -> None:
    """Restrict the main SQLite file and any existing WAL sidecars to the owner."""

    for _, _, database_name in connection.execute("PRAGMA database_list").fetchall():
        if not database_name:
            continue
        database = Path(database_name)
        for candidate in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
            if candidate.exists():
                candidate.chmod(0o600)
