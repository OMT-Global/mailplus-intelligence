"""Promotion queue with immutable artifacts and append-only review history."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .semantic_contract import MAX_SUMMARY_CHARS, SemanticArtifact


REVIEW_STATES = frozenset(
    {
        "candidate",
        "review_needed",
        "approved",
        "rejected",
        "deferred",
        "corrected",
        "rollback_needed",
    }
)
TERMINAL_STATES = frozenset({"rejected", "rollback_needed"})
EXPORT_ELIGIBLE_STATES = frozenset({"approved", "corrected"})
MAX_REVIEWER_IDENTITY_CHARS = 320
MAX_REVIEW_NOTES_CHARS = 512
_FAILURE_CODE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SENSITIVE_AUDIT_TEXT = re.compile(
    r"(?i)(?:sk-(?:live|proj)-|ghp" + r"_|github_pat" + r"_|bearer\s+|"
    r"\b(?:api[_-]?key|authorization|cookie|password|secret|session|token)\s*[:=])"
)

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"review_needed", "approved", "rejected", "deferred", "corrected"}),
    "review_needed": frozenset({"candidate", "approved", "rejected", "deferred", "corrected"}),
    "deferred": frozenset({"candidate", "review_needed", "approved", "rejected", "corrected"}),
    "approved": frozenset({"corrected", "rollback_needed"}),
    "corrected": frozenset({"rollback_needed"}),
    "rejected": frozenset(),
    "rollback_needed": frozenset(),
}


class ReviewDecisionError(ValueError):
    """Base error for invalid review operations."""


class InvalidReviewTransitionError(ReviewDecisionError):
    """Raised when a requested review state transition is not legal."""


class StaleReviewDecisionError(ReviewDecisionError):
    """Raised when the caller reviewed an older artifact revision."""


@dataclass(frozen=True)
class QueueItem:
    """Current queue snapshot plus its immutable semantic envelope."""

    artifact_id: str
    artifact_type: str
    source_message_ids: list[str]
    source_locators: list[Any]
    evidence_refs: list[str]
    source_thread_key: str
    summary: str
    confidence: str
    provenance: str
    extractor_version: str
    model_version: str | None
    rule_version: str | None
    created_at: str
    initial_review_status: str
    review_status: str
    revision: int
    latest_review_event_id: str | None
    reviewer_identity: str | None
    reviewer_notes: str | None
    corrected_summary: str | None
    queued_at: str
    decided_at: str | None

    def semantic_dict(self) -> dict[str, Any]:
        """Return the extraction-time artifact for validation or export."""

        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "source_thread_key": self.source_thread_key,
            "source_message_ids": list(self.source_message_ids),
            "source_locators": list(self.source_locators),
            "evidence_refs": list(self.evidence_refs),
            "summary": self.summary,
            "confidence": self.confidence,
            "review_status": self.initial_review_status,
            "provenance": self.provenance,
            "extractor_version": self.extractor_version,
            "model_version": self.model_version,
            "rule_version": self.rule_version,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ReviewEvent:
    """One append-only review decision."""

    event_id: str
    artifact_id: str
    artifact_revision: int
    event_type: str
    prior_status: str
    new_status: str
    reviewer_identity: str
    reviewer_notes: str | None
    corrected_summary: str | None
    occurred_at: str


@dataclass(frozen=True)
class OutboxItem:
    """Durable idempotency and rollback state for one export target."""

    outbox_id: str
    artifact_id: str
    artifact_revision: int
    review_event_id: str
    export_type: str
    target_key: str
    idempotency_key: str
    content_hash: str
    state: str
    target_metadata: dict[str, Any]
    rollback_note: str | None
    failure_code: str | None
    created_at: str
    updated_at: str
    exported_at: str | None
    rollback_requested_at: str | None
    rolled_back_at: str | None


def enqueue_candidate(connection: sqlite3.Connection, artifact: dict[str, Any] | object) -> str:
    """Validate and add an immutable semantic artifact to the review queue."""

    envelope = SemanticArtifact.from_value(artifact)
    value = envelope.to_dict()
    queued_at = _utc_now()

    with _owned_transaction(connection, "enqueue candidate"):
        connection.execute(
            """
            INSERT INTO promotion_queue (
              artifact_id, artifact_type, source_message_ids, source_locators,
              evidence_refs, source_thread_key, summary, confidence, provenance,
              extractor_version, model_version, rule_version, artifact_created_at,
              initial_review_status, review_status, revision, queued_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                value["artifact_id"],
                value["artifact_type"],
                _json(value["source_message_ids"]),
                _json(value["source_locators"]),
                _json(value["evidence_refs"]),
                value["source_thread_key"],
                value["summary"],
                value["confidence"],
                value["provenance"],
                value["extractor_version"],
                value["model_version"],
                value["rule_version"],
                value["created_at"],
                value["review_status"],
                value["review_status"],
                queued_at,
            ),
        )
    return envelope.artifact_id


def decide(
    connection: sqlite3.Connection,
    artifact_id: str,
    decision: str,
    reviewer_notes: str | None = None,
    corrected_summary: str | None = None,
    *,
    reviewer_identity: str,
    expected_revision: int,
) -> ReviewEvent:
    """Append a legal review decision using optimistic revision checking."""

    if decision not in REVIEW_STATES:
        raise ReviewDecisionError(
            f"invalid decision {decision!r}; expected one of {sorted(REVIEW_STATES)}"
        )
    normalized_reviewer = reviewer_identity.strip() if isinstance(reviewer_identity, str) else ""
    if not normalized_reviewer:
        raise ReviewDecisionError("reviewer_identity is required")
    if (
        len(normalized_reviewer) > MAX_REVIEWER_IDENTITY_CHARS
        or "\n" in normalized_reviewer
        or "\r" in normalized_reviewer
        or "\x00" in normalized_reviewer
    ):
        raise ReviewDecisionError("reviewer_identity is invalid")
    if reviewer_notes is not None and not _privacy_safe_audit_text(reviewer_notes):
        raise ReviewDecisionError(
            "reviewer_notes must be a bounded, single-line, privacy-safe audit note"
        )
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        raise ReviewDecisionError("expected_revision must be a non-negative integer")
    if decision == "corrected" and (not corrected_summary or not corrected_summary.strip()):
        raise ReviewDecisionError("corrected_summary is required for a corrected decision")
    if corrected_summary is not None and len(corrected_summary) > MAX_SUMMARY_CHARS:
        raise ReviewDecisionError("corrected_summary exceeds maximum length")
    if decision != "corrected" and corrected_summary is not None:
        raise ReviewDecisionError("corrected_summary is only valid for a corrected decision")
    if decision == "rollback_needed" and (not reviewer_notes or not reviewer_notes.strip()):
        raise ReviewDecisionError("reviewer_notes are required when rollback is requested")

    with _owned_transaction(connection, "record review decision"):
        row = connection.execute(
            """
            SELECT review_status, revision, corrected_summary
            FROM promotion_queue
            WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"artifact_id not found: {artifact_id}")

        current_status = row["review_status"]
        current_revision = int(row["revision"])
        if current_revision != expected_revision:
            raise StaleReviewDecisionError(
                f"stale review for {artifact_id}: expected revision {expected_revision}, "
                f"current revision is {current_revision}"
            )
        if decision not in LEGAL_TRANSITIONS[current_status]:
            raise InvalidReviewTransitionError(
                f"illegal review transition for {artifact_id}: {current_status} -> {decision}"
            )

        new_revision = current_revision + 1
        event_id = str(uuid.uuid4())
        occurred_at = _utc_now()
        next_correction = corrected_summary if decision == "corrected" else None
        if decision == "rollback_needed":
            next_correction = row["corrected_summary"]

        connection.execute(
            """
            INSERT INTO review_events (
              event_id, artifact_id, artifact_revision, event_type,
              prior_status, new_status, reviewer_identity, reviewer_notes,
              corrected_summary, occurred_at
            ) VALUES (?, ?, ?, 'review.decision', ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                artifact_id,
                new_revision,
                current_status,
                decision,
                normalized_reviewer,
                reviewer_notes,
                next_correction,
                occurred_at,
            ),
        )

        cursor = connection.execute(
            """
            UPDATE promotion_queue
            SET review_status = ?, revision = ?, latest_review_event_id = ?,
                reviewer_identity = ?, reviewer_notes = ?, corrected_summary = ?,
                decided_at = ?
            WHERE artifact_id = ? AND revision = ? AND review_status = ?
            """,
            (
                decision,
                new_revision,
                event_id,
                normalized_reviewer,
                reviewer_notes,
                next_correction,
                occurred_at,
                artifact_id,
                expected_revision,
                current_status,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleReviewDecisionError(
                f"review state changed while deciding {artifact_id}; reload and retry"
            )

        if current_status in EXPORT_ELIGIBLE_STATES:
            rollback_note = reviewer_notes or (
                f"Superseded by {decision} review revision {new_revision}."
            )
            connection.execute(
                """
                UPDATE export_outbox
                SET state = 'rollback_needed', rollback_note = ?,
                    rollback_requested_at = ?, updated_at = ?
                WHERE artifact_id = ? AND state IN ('planned', 'exported')
                """,
                (rollback_note, occurred_at, occurred_at, artifact_id),
            )

    return ReviewEvent(
        event_id=event_id,
        artifact_id=artifact_id,
        artifact_revision=new_revision,
        event_type="review.decision",
        prior_status=current_status,
        new_status=decision,
        reviewer_identity=normalized_reviewer,
        reviewer_notes=reviewer_notes,
        corrected_summary=next_correction,
        occurred_at=occurred_at,
    )


def get_queue(
    connection: sqlite3.Connection,
    status: str | None = None,
    artifact_type: str | None = None,
    limit: int = 100,
) -> list[QueueItem]:
    """List queue items filtered by current status and/or type."""

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
    return [_queue_item(row) for row in rows]


def get_item(connection: sqlite3.Connection, artifact_id: str) -> QueueItem | None:
    """Fetch a single queue item by artifact ID."""

    row = connection.execute(
        "SELECT * FROM promotion_queue WHERE artifact_id = ?", (artifact_id,)
    ).fetchone()
    return None if row is None else _queue_item(row)


def get_review_history(connection: sqlite3.Connection, artifact_id: str) -> list[ReviewEvent]:
    """Return append-only review events in revision order."""

    rows = connection.execute(
        """
        SELECT * FROM review_events
        WHERE artifact_id = ?
        ORDER BY artifact_revision ASC
        """,
        (artifact_id,),
    ).fetchall()
    return [_review_event(row) for row in rows]


def reserve_outbox(
    connection: sqlite3.Connection,
    item: QueueItem,
    *,
    export_type: str,
    target_key: str,
    content_hash: str,
    rollback_note: str | None,
) -> OutboxItem:
    """Reserve or return the stable export identity for an approved revision."""

    if not item.latest_review_event_id or item.revision <= 0:
        raise ReviewDecisionError("export requires an append-only review decision")
    identity = "\0".join(
        (item.artifact_id, str(item.revision), export_type, target_key)
    )
    idempotency_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    outbox_id = f"outbox-{idempotency_key[:32]}"
    now = _utc_now()

    with _owned_transaction(connection, "reserve export outbox"):
        connection.execute(
            """
            INSERT INTO export_outbox (
              outbox_id, artifact_id, artifact_revision, review_event_id,
              export_type, target_key, idempotency_key, content_hash, state,
              target_metadata, rollback_note, created_at, updated_at
            )
            SELECT ?, artifact_id, revision, latest_review_event_id,
                   ?, ?, ?, ?, 'planned', '{}', ?, ?, ?
            FROM promotion_queue
            WHERE artifact_id = ?
              AND revision = ?
              AND latest_review_event_id = ?
              AND review_status IN ('approved', 'corrected')
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (
                outbox_id,
                export_type,
                target_key,
                idempotency_key,
                content_hash,
                rollback_note,
                now,
                now,
                item.artifact_id,
                item.revision,
                item.latest_review_event_id,
            ),
        )

    outbox = get_outbox(connection, outbox_id)
    if outbox is None:
        raise ReviewDecisionError(
            f"artifact review changed before export reservation: {item.artifact_id}"
        )
    if outbox.content_hash != content_hash:
        raise RuntimeError(
            f"idempotency collision for {item.artifact_id} revision {item.revision}"
        )
    return outbox


def get_outbox(connection: sqlite3.Connection, outbox_id: str) -> OutboxItem | None:
    """Return one export outbox record."""

    row = connection.execute(
        "SELECT * FROM export_outbox WHERE outbox_id = ?", (outbox_id,)
    ).fetchone()
    return None if row is None else _outbox_item(row)


def mark_outbox_exported(
    connection: sqlite3.Connection,
    outbox_id: str,
    *,
    target_metadata: dict[str, Any] | None = None,
) -> OutboxItem:
    """Record a successful idempotent export."""

    now = _utc_now()
    with _owned_transaction(connection, "mark outbox exported"):
        cursor = connection.execute(
            """
            UPDATE export_outbox
            SET state = 'exported', target_metadata = ?, failure_code = NULL,
                exported_at = COALESCE(exported_at, ?), updated_at = ?
            WHERE outbox_id = ? AND state IN ('planned', 'failed', 'exported')
              AND EXISTS (
                SELECT 1
                FROM promotion_queue
                WHERE promotion_queue.artifact_id = export_outbox.artifact_id
                  AND promotion_queue.revision = export_outbox.artifact_revision
                  AND promotion_queue.latest_review_event_id = export_outbox.review_event_id
                  AND promotion_queue.review_status IN ('approved', 'corrected')
              )
            """,
            (_json(target_metadata or {}), now, now, outbox_id),
        )
        if cursor.rowcount != 1:
            raise ReviewDecisionError(
                f"outbox {outbox_id} cannot be exported from its current state"
            )
    return _required_outbox(connection, outbox_id)


def mark_outbox_failed(
    connection: sqlite3.Connection,
    outbox_id: str,
    *,
    failure_code: str,
) -> OutboxItem:
    """Record a privacy-safe export failure code for retry."""

    normalized_failure_code = failure_code.strip() if isinstance(failure_code, str) else ""
    if not _FAILURE_CODE.fullmatch(normalized_failure_code):
        raise ValueError("failure_code must be a bounded privacy-safe reason code")
    now = _utc_now()
    with _owned_transaction(connection, "mark outbox failed"):
        cursor = connection.execute(
            """
            UPDATE export_outbox
            SET state = 'failed', failure_code = ?, updated_at = ?
            WHERE outbox_id = ? AND state IN ('planned', 'failed')
            """,
            (normalized_failure_code, now, outbox_id),
        )
        if cursor.rowcount != 1:
            raise ReviewDecisionError(
                f"outbox {outbox_id} cannot fail from its current state"
            )
    return _required_outbox(connection, outbox_id)


def mark_outbox_rolled_back(connection: sqlite3.Connection, outbox_id: str) -> OutboxItem:
    """Record completion of an explicitly requested rollback."""

    now = _utc_now()
    with _owned_transaction(connection, "mark outbox rolled back"):
        cursor = connection.execute(
            """
            UPDATE export_outbox
            SET state = 'rolled_back', rolled_back_at = ?, updated_at = ?
            WHERE outbox_id = ? AND state = 'rollback_needed'
            """,
            (now, now, outbox_id),
        )
        if cursor.rowcount != 1:
            raise ReviewDecisionError(
                f"outbox {outbox_id} is not awaiting rollback"
            )
    return _required_outbox(connection, outbox_id)


def _queue_item(row: sqlite3.Row) -> QueueItem:
    return QueueItem(
        artifact_id=row["artifact_id"],
        artifact_type=row["artifact_type"],
        source_message_ids=_json_list(row["source_message_ids"]),
        source_locators=_json_list(row["source_locators"]),
        evidence_refs=_json_list(row["evidence_refs"]),
        source_thread_key=row["source_thread_key"],
        summary=row["summary"],
        confidence=row["confidence"],
        provenance=row["provenance"],
        extractor_version=row["extractor_version"],
        model_version=row["model_version"],
        rule_version=row["rule_version"],
        created_at=row["artifact_created_at"],
        initial_review_status=row["initial_review_status"],
        review_status=row["review_status"],
        revision=int(row["revision"]),
        latest_review_event_id=row["latest_review_event_id"],
        reviewer_identity=row["reviewer_identity"],
        reviewer_notes=row["reviewer_notes"],
        corrected_summary=row["corrected_summary"],
        queued_at=row["queued_at"],
        decided_at=row["decided_at"],
    )


def _review_event(row: sqlite3.Row) -> ReviewEvent:
    return ReviewEvent(
        event_id=row["event_id"],
        artifact_id=row["artifact_id"],
        artifact_revision=int(row["artifact_revision"]),
        event_type=row["event_type"],
        prior_status=row["prior_status"],
        new_status=row["new_status"],
        reviewer_identity=row["reviewer_identity"],
        reviewer_notes=row["reviewer_notes"],
        corrected_summary=row["corrected_summary"],
        occurred_at=row["occurred_at"],
    )


def _outbox_item(row: sqlite3.Row) -> OutboxItem:
    return OutboxItem(
        outbox_id=row["outbox_id"],
        artifact_id=row["artifact_id"],
        artifact_revision=int(row["artifact_revision"]),
        review_event_id=row["review_event_id"],
        export_type=row["export_type"],
        target_key=row["target_key"],
        idempotency_key=row["idempotency_key"],
        content_hash=row["content_hash"],
        state=row["state"],
        target_metadata=json.loads(row["target_metadata"]),
        rollback_note=row["rollback_note"],
        failure_code=row["failure_code"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        exported_at=row["exported_at"],
        rollback_requested_at=row["rollback_requested_at"],
        rolled_back_at=row["rolled_back_at"],
    )


def _required_outbox(connection: sqlite3.Connection, outbox_id: str) -> OutboxItem:
    outbox = get_outbox(connection, outbox_id)
    if outbox is None:
        raise KeyError(f"outbox_id not found: {outbox_id}")
    return outbox


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_list(value: str) -> list[Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("stored semantic collection is not a JSON array")
    return parsed


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _privacy_safe_audit_text(value: str) -> bool:
    return (
        len(value) <= MAX_REVIEW_NOTES_CHARS
        and "\n" not in value
        and "\r" not in value
        and "\x00" not in value
        and not _SENSITIVE_AUDIT_TEXT.search(value)
    )


@contextmanager
def _owned_transaction(connection: sqlite3.Connection, operation: str) -> Iterator[None]:
    """Run one queue mutation without committing a caller-owned transaction."""

    if connection.in_transaction:
        raise ReviewDecisionError(
            f"{operation} requires a clean connection with no active caller transaction"
        )
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
