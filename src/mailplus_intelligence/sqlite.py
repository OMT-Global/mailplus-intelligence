"""SQLite connection helpers for local metadata/index foundations."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_sqlite(database: str | Path = ":memory:") -> sqlite3.Connection:
    """Open a SQLite connection with project defaults for index work."""

    database_name = str(database)
    connection = sqlite3.connect(database_name)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    if database_name != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")

    return connection
