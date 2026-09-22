"""Incremental sync job with checkpoint management.

Reads fixture batches (or live adapter batches via the same interface),
writes to the SQLite index idempotently, and updates sync_checkpoints.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .index_writer import WriteResult, write_index_records
from .ingest import IngestDecision, prepare_ingest


@dataclass(frozen=True)
class SyncBatch:
    """A batch of raw message dicts ready for sync processing."""

    source_name: str
    cursor: str
    messages: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SyncRejection:
    """Privacy-safe quarantine metadata for a rejected source record."""

    source_name: str
    cursor: str
    fixture_id: str
    code: str
    reason: str


@dataclass(frozen=True)
class SyncResult:
    """Summary of one sync batch run with every source record accounted for."""

    source_name: str
    cursor: str
    inserted: int
    updated: int
    unchanged: int
    rejected: int
    failed: int
    mapper_issues: int
    write_errors: tuple[str, ...]
    rejections: tuple[SyncRejection, ...]
    success: bool
    dry_run: bool
    committed: bool
    checkpoint_advanced: bool
    completed_at: str

    @property
    def skipped(self) -> int:
        """Compatibility alias for callers that previously reported skips."""

        return self.unchanged

    @property
    def accounted(self) -> int:
        """Number of input records represented by the outcome counts."""

        return (
            self.inserted
            + self.updated
            + self.unchanged
            + self.rejected
            + self.failed
        )


def run_sync_batch(
    connection: sqlite3.Connection,
    batch: SyncBatch,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Process one sync batch against the index.

    Mapping and normalized-record validation happen before mutation. The
    documented idempotency identity is ``locator_export_id``; matching metadata
    is unchanged and drifted metadata is updated. Applied data and checkpoint
    advancement share one transaction and are rolled back together on failure.
    """
    prepared = prepare_ingest(list(batch.messages))
    planned = write_index_records(connection, prepared.records, dry_run=True)
    rejections = tuple(
        SyncRejection(
            source_name=batch.source_name,
            cursor=batch.cursor,
            fixture_id=issue.fixture_id,
            code=issue.code,
            reason=issue.message,
        )
        for issue in prepared.mapper.rejections
    )

    if dry_run or rejections or planned.failed:
        return _sync_result(
            batch,
            planned,
            mapper_issues=len(prepared.mapper.issues),
            rejections=rejections,
            success=not rejections and planned.failed == 0,
            dry_run=dry_run,
            committed=False,
            checkpoint_advanced=False,
        )

    savepoint = "sync_batch"
    connection.execute(f"SAVEPOINT {savepoint}")
    write_result = planned
    try:
        write_result = write_index_records(
            connection,
            prepared.records,
            commit=False,
        )
        if write_result.failed:
            _rollback_savepoint(connection, savepoint)
            connection.commit()
            return _sync_result(
                batch,
                write_result,
                mapper_issues=len(prepared.mapper.issues),
                rejections=rejections,
                success=False,
                dry_run=False,
                committed=False,
                checkpoint_advanced=False,
            )

        _persist_ingest_decisions(connection, prepared.decisions)
        _record_locator_history(connection, prepared.records)
        _update_checkpoint(connection, batch.source_name, batch.cursor)
    except Exception as exc:
        _rollback_savepoint(connection, savepoint)
        connection.commit()
        return _sync_result(
            batch,
            write_result,
            mapper_issues=len(prepared.mapper.issues),
            rejections=rejections,
            success=False,
            dry_run=False,
            committed=False,
            checkpoint_advanced=False,
            additional_errors=(f"batch transaction: {exc}",),
        )

    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
    connection.commit()
    return _sync_result(
        batch,
        write_result,
        mapper_issues=len(prepared.mapper.issues),
        rejections=rejections,
        success=True,
        dry_run=False,
        committed=True,
        checkpoint_advanced=True,
    )


def _sync_result(
    batch: SyncBatch,
    write_result: WriteResult,
    *,
    mapper_issues: int,
    rejections: tuple[SyncRejection, ...],
    success: bool,
    dry_run: bool,
    committed: bool,
    checkpoint_advanced: bool,
    additional_errors: tuple[str, ...] = (),
) -> SyncResult:
    return SyncResult(
        source_name=batch.source_name,
        cursor=batch.cursor,
        inserted=write_result.inserted,
        updated=write_result.updated,
        unchanged=write_result.unchanged,
        rejected=len(rejections),
        failed=write_result.failed,
        mapper_issues=mapper_issues,
        write_errors=write_result.errors + additional_errors,
        rejections=rejections,
        success=success,
        dry_run=dry_run,
        committed=committed,
        checkpoint_advanced=checkpoint_advanced,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _rollback_savepoint(connection: sqlite3.Connection, savepoint: str) -> None:
    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
    connection.execute(f"RELEASE SAVEPOINT {savepoint}")


def get_checkpoint(connection: sqlite3.Connection, source_name: str) -> dict | None:
    """Return the current checkpoint dict for a source, or None if not started."""
    row = connection.execute(
        "SELECT * FROM sync_checkpoints WHERE source_name = ?", (source_name,)
    ).fetchone()
    return dict(row) if row else None


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


def _persist_ingest_decisions(
    connection: sqlite3.Connection, decisions: tuple[IngestDecision, ...]
) -> None:
    """Persist the one decision that downstream extraction must consume."""

    for decision in decisions:
        connection.execute(
            """
            INSERT INTO ingest_decisions (
              locator_export_id, thread_key, lane, thread_confidence,
              suppression_action, extraction_eligible, reason_codes,
              source_state, decided_at, last_seen_at, missing_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'present', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)
            ON CONFLICT(locator_export_id) DO UPDATE SET
              thread_key = excluded.thread_key,
              lane = excluded.lane,
              thread_confidence = excluded.thread_confidence,
              suppression_action = excluded.suppression_action,
              extraction_eligible = excluded.extraction_eligible,
              reason_codes = excluded.reason_codes,
              source_state = 'present',
              decided_at = CURRENT_TIMESTAMP,
              last_seen_at = CURRENT_TIMESTAMP,
              missing_at = NULL
            """,
            (
                decision.locator_export_id,
                decision.thread_key,
                decision.lane,
                decision.confidence,
                decision.suppression_action,
                int(decision.extraction_eligible),
                ",".join(decision.reason_codes),
            ),
        )


def _record_locator_history(connection: sqlite3.Connection, records: tuple[object, ...]) -> None:
    """Append-only locator variants preserve moves without deleting history."""

    for record in records:
        connection.execute(
            """
            INSERT OR IGNORE INTO message_locator_history (
              locator_export_id, account, mailbox, folder_path, locator_uid, source_state
            ) VALUES (?, ?, ?, ?, ?, 'present')
            """,
            (
                record.locator_export_id,
                record.locator_account,
                record.locator_mailbox,
                record.locator_folder,
                record.locator_uid,
            ),
        )


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
