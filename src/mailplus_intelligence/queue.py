"""Promotion review queue for extracted semantic candidates."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


TERMINAL_STATES = frozenset({"approved", "rejected", "deferred", "corrected", "rollback_needed"})


@dataclass(frozen=True)
class QueueItem:
    """A single item in the promotion review queue."""

    artifact_id: str
    artifact_type: str
    source_locators: list[str]
    source_thread_key: str
    summary: str
    confidence: str
    provenance: str
    review_status: str
    reviewer_notes: str | None
    corrected_summary: str | None
    queued_at: str
    decided_at: str | None


def enqueue_candidate(
    connection: sqlite3.Connection,
    artifact: dict[str, Any],
) -> str:
    """Add a semantic artifact candidate to the review queue.

    Returns the artifact_id (generated if not provided).
    """
    artifact_id = str(artifact.get("artifact_id") or uuid.uuid4())
    source_locators = artifact.get("source_locators", [])
    now = datetime.now(timezone.utc).isoformat()

    connection.execute(
        """
        INSERT INTO promotion_queue (
          artifact_id, artifact_type, source_locators, source_thread_key,
          summary, confidence, provenance, review_status, queued_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?)
        """,
        (
            artifact_id,
            str(artifact.get("artifact_type", "")),
            json.dumps(source_locators),
            str(artifact.get("source_thread_key", "")),
            str(artifact.get("summary", "")),
            str(artifact.get("confidence", "low")),
            json.dumps(artifact.get("evidence_refs", [])),
            now,
        ),
    )
    connection.commit()
    return artifact_id


def decide(
    connection: sqlite3.Connection,
    artifact_id: str,
    decision: str,
    reviewer_notes: str | None = None,
    corrected_summary: str | None = None,
) -> None:
    """Apply a review decision to a queued candidate."""

    allowed = {"approved", "rejected", "deferred", "corrected", "rollback_needed", "review_needed"}
    if decision not in allowed:
        raise ValueError(f"Invalid decision '{decision}'. Must be one of: {sorted(allowed)}")

    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE promotion_queue
        SET review_status = ?, reviewer_notes = ?, corrected_summary = ?, decided_at = ?
        WHERE artifact_id = ?
        """,
        (decision, reviewer_notes, corrected_summary, now, artifact_id),
    )
    if connection.execute(
        "SELECT changes()"
    ).fetchone()[0] == 0:
        raise KeyError(f"artifact_id not found: {artifact_id}")
    connection.commit()


def get_queue(
    connection: sqlite3.Connection,
    status: str | None = None,
    artifact_type: str | None = None,
    limit: int = 100,
) -> list[QueueItem]:
    """List queue items filtered by status and/or type."""

    clauses: list[str] = []
    params: list[object] = []
    if status:
        clauses.append("review_status = ?")
        params.append(status)
    if artifact_type:
        clauses.append("artifact_type = ?")
        params.append(artifact_type)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    rows = connection.execute(
        f"SELECT * FROM promotion_queue {where} ORDER BY queued_at DESC LIMIT ?",
        params,
    ).fetchall()

    return [
        QueueItem(
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            source_locators=json.loads(row["source_locators"]),
            source_thread_key=row["source_thread_key"],
            summary=row["summary"],
            confidence=row["confidence"],
            provenance=row["provenance"],
            review_status=row["review_status"],
            reviewer_notes=row["reviewer_notes"],
            corrected_summary=row["corrected_summary"],
            queued_at=row["queued_at"],
            decided_at=row["decided_at"],
        )
        for row in rows
    ]


def get_item(connection: sqlite3.Connection, artifact_id: str) -> QueueItem | None:
    """Fetch a single queue item by artifact_id."""

    row = connection.execute(
        "SELECT * FROM promotion_queue WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    if row is None:
        return None
    return QueueItem(
        artifact_id=row["artifact_id"],
        artifact_type=row["artifact_type"],
        source_locators=json.loads(row["source_locators"]),
        source_thread_key=row["source_thread_key"],
        summary=row["summary"],
        confidence=row["confidence"],
        provenance=row["provenance"],
        review_status=row["review_status"],
        reviewer_notes=row["reviewer_notes"],
        corrected_summary=row["corrected_summary"],
        queued_at=row["queued_at"],
        decided_at=row["decided_at"],
    )
