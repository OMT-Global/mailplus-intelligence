"""Incremental sync job with checkpoint management.

Reads fixture batches (or live adapter batches via the same interface),
writes to the SQLite index idempotently, and updates sync_checkpoints.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .index_writer import write_index_records
from .mapper import map_fixture_messages


@dataclass(frozen=True)
class SyncBatch:
    """A batch of raw message dicts ready for sync processing."""

    source_name: str
    cursor: str
    messages: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SyncResult:
    """Summary of one sync batch run."""

    source_name: str
    cursor: str
    inserted: int
    skipped: int
    mapper_issues: int
    write_errors: tuple[str, ...]
    success: bool
    completed_at: str


def run_sync_batch(
    connection: sqlite3.Connection,
    batch: SyncBatch,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Process one sync batch against the index.

    Idempotent: messages whose locator_export_id is already indexed are skipped.
    Updates sync_checkpoints on success.
    """
    _record_attempt(connection, batch.source_name)

    map_result = map_fixture_messages(list(batch.messages))

    if dry_run:
        return SyncResult(
            source_name=batch.source_name,
            cursor=batch.cursor,
            inserted=0,
            skipped=len(map_result.records),
            mapper_issues=len(map_result.issues),
            write_errors=(),
            success=True,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    write_result = write_index_records(connection, map_result.records)

    if not write_result.errors:
        _update_checkpoint(connection, batch.source_name, batch.cursor)

    completed_at = datetime.now(timezone.utc).isoformat()
    return SyncResult(
        source_name=batch.source_name,
        cursor=batch.cursor,
        inserted=write_result.inserted,
        skipped=write_result.skipped,
        mapper_issues=len(map_result.issues),
        write_errors=write_result.errors,
        success=len(write_result.errors) == 0,
        completed_at=completed_at,
    )


def get_checkpoint(connection: sqlite3.Connection, source_name: str) -> dict | None:
    """Return the current checkpoint dict for a source, or None if not started."""
    row = connection.execute(
        "SELECT * FROM sync_checkpoints WHERE source_name = ?", (source_name,)
    ).fetchone()
    return dict(row) if row else None


def _record_attempt(connection: sqlite3.Connection, source_name: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO sync_checkpoints (source_name, cursor, last_attempt_at)
        VALUES (?, '', ?)
        ON CONFLICT(source_name) DO UPDATE SET last_attempt_at = excluded.last_attempt_at
        """,
        (source_name, now),
    )
    connection.commit()


def _update_checkpoint(
    connection: sqlite3.Connection, source_name: str, cursor: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO sync_checkpoints (source_name, cursor, last_success_at, last_attempt_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_name) DO UPDATE SET
          cursor = excluded.cursor,
          last_success_at = excluded.last_success_at,
          last_attempt_at = excluded.last_attempt_at
        """,
        (source_name, cursor, now, now),
    )
    connection.commit()


def sync_from_fixture_corpus(
    connection: sqlite3.Connection,
    corpus_dir: str,
    source_name: str = "fixture-corpus",
) -> SyncResult:
    """Convenience: sync all messages from a fixture corpus directory."""
    from .fixtures import load_metadata_fixture_corpus

    corpus = load_metadata_fixture_corpus(corpus_dir)
    batch = SyncBatch(
        source_name=source_name,
        cursor=f"fixture-v{corpus.version}",
        messages=corpus.messages,
    )
    return run_sync_batch(connection, batch)
