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

    return connection
