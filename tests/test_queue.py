"""Tests for canonical promotion artifacts and append-only review history."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from importlib import resources
from pathlib import Path

from mailplus_intelligence.queue import (
    InvalidReviewTransitionError,
    ReviewDecisionError,
    StaleReviewDecisionError,
    decide,
    enqueue_candidate,
    get_item,
    get_queue,
    get_review_history,
)
from mailplus_intelligence.schema import (
    apply_all_migrations,
    current_schema_version,
)
from mailplus_intelligence.semantic_contract import SemanticArtifactValidationError
from mailplus_intelligence.sqlite import connect_sqlite


SAMPLE_ARTIFACT = {
    "artifact_type": "obligation",
    "source_thread_key": "thread-a",
    "source_message_ids": ["<atlas-001@example.test>"],
    "source_locators": [
        {"locator_export_id": "fixture-export-001", "locator_uid": "1001"}
    ],
    "evidence_refs": ["subject"],
    "summary": "Alice committed to delivering the Atlas plan by end of week.",
    "confidence": "high",
    "review_status": "candidate",
    "provenance": "deterministic",
    "extractor_version": "metadata-extractor-v1",
    "model_version": None,
    "rule_version": "metadata-rules-v1",
    "created_at": "2026-01-10T10:00:00Z",
}


class PromotionQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_enqueue_round_trips_every_canonical_field(self) -> None:
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        item = get_item(self.conn, artifact_id)

        self.assertIsNotNone(item)
        self.assertEqual(item.artifact_type, SAMPLE_ARTIFACT["artifact_type"])
        self.assertEqual(item.source_message_ids, SAMPLE_ARTIFACT["source_message_ids"])
        self.assertEqual(item.source_locators, SAMPLE_ARTIFACT["source_locators"])
        self.assertEqual(item.evidence_refs, SAMPLE_ARTIFACT["evidence_refs"])
        self.assertEqual(item.source_thread_key, SAMPLE_ARTIFACT["source_thread_key"])
        self.assertEqual(item.summary, SAMPLE_ARTIFACT["summary"])
        self.assertEqual(item.confidence, SAMPLE_ARTIFACT["confidence"])
        self.assertEqual(item.provenance, SAMPLE_ARTIFACT["provenance"])
        self.assertEqual(item.extractor_version, SAMPLE_ARTIFACT["extractor_version"])
        self.assertEqual(item.model_version, SAMPLE_ARTIFACT["model_version"])
        self.assertEqual(item.rule_version, SAMPLE_ARTIFACT["rule_version"])
        self.assertEqual(item.created_at, SAMPLE_ARTIFACT["created_at"])
        self.assertEqual(item.initial_review_status, "candidate")
        self.assertEqual(item.review_status, "candidate")
        self.assertEqual(item.revision, 0)

    def test_review_needed_is_not_rewritten(self) -> None:
        artifact_id = enqueue_candidate(
            self.conn,
            {**SAMPLE_ARTIFACT, "review_status": "review_needed"},
        )

        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.initial_review_status, "review_needed")
        self.assertEqual(item.review_status, "review_needed")

    def test_llm_provenance_round_trips_model(self) -> None:
        artifact_id = enqueue_candidate(
            self.conn,
            {
                **SAMPLE_ARTIFACT,
                "provenance": "llm",
                "model_version": "claude-test",
                "rule_version": None,
            },
        )

        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.provenance, "llm")
        self.assertEqual(item.model_version, "claude-test")
        self.assertIsNone(item.rule_version)

    def test_invalid_artifact_is_rejected_before_persistence(self) -> None:
        for field, value in (
            ("artifact_type", "unknown"),
            ("confidence", "certain"),
            ("provenance", "remote"),
            ("review_status", "approved"),
        ):
            with self.subTest(field=field), self.assertRaises(SemanticArtifactValidationError):
                enqueue_candidate(self.conn, {**SAMPLE_ARTIFACT, field: value})

        count = self.conn.execute("SELECT COUNT(*) FROM promotion_queue").fetchone()[0]
        self.assertEqual(count, 0)

    def test_review_decision_is_append_only_and_identified(self) -> None:
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        event = decide(
            self.conn,
            artifact_id,
            "approved",
            reviewer_notes="Evidence confirmed",
            reviewer_identity="reviewer@example.test",
            expected_revision=0,
        )

        item = get_item(self.conn, artifact_id)
        history = get_review_history(self.conn, artifact_id)
        self.assertEqual(item.review_status, "approved")
        self.assertEqual(item.revision, 1)
        self.assertEqual(item.latest_review_event_id, event.event_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].reviewer_identity, "reviewer@example.test")
        self.assertEqual(history[0].prior_status, "candidate")
        self.assertEqual(history[0].new_status, "approved")

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE review_events SET reviewer_identity = 'changed' WHERE event_id = ?",
                (event.event_id,),
            )
        self.conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM review_events WHERE event_id = ?", (event.event_id,))
        self.conn.rollback()

    def test_correction_preserves_original_and_records_replacement(self) -> None:
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        decide(
            self.conn,
            artifact_id,
            "corrected",
            corrected_summary="Alice committed to delivery on Friday.",
            reviewer_notes="Date was explicit in the source metadata.",
            reviewer_identity="operator",
            expected_revision=0,
        )

        item = get_item(self.conn, artifact_id)
        event = get_review_history(self.conn, artifact_id)[0]
        self.assertEqual(item.summary, SAMPLE_ARTIFACT["summary"])
        self.assertEqual(item.corrected_summary, "Alice committed to delivery on Friday.")
        self.assertEqual(event.corrected_summary, item.corrected_summary)

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE promotion_queue SET summary = 'mutated' WHERE artifact_id = ?",
                (artifact_id,),
            )
        self.conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "DELETE FROM promotion_queue WHERE artifact_id = ?",
                (artifact_id,),
            )
        self.conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "UPDATE promotion_queue SET corrected_summary = 'unreviewed' WHERE artifact_id = ?",
                (artifact_id,),
            )
        self.conn.rollback()

    def test_illegal_and_stale_transitions_fail(self) -> None:
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        decide(
            self.conn,
            artifact_id,
            "rejected",
            reviewer_identity="operator",
            expected_revision=0,
        )

        with self.assertRaises(StaleReviewDecisionError):
            decide(
                self.conn,
                artifact_id,
                "approved",
                reviewer_identity="operator",
                expected_revision=0,
            )
        with self.assertRaises(InvalidReviewTransitionError):
            decide(
                self.conn,
                artifact_id,
                "approved",
                reviewer_identity="operator",
                expected_revision=1,
            )
        self.assertEqual(len(get_review_history(self.conn, artifact_id)), 1)

    def test_concurrent_review_uses_optimistic_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "queue.db"
            first = connect_sqlite(database)
            second = connect_sqlite(database)
            try:
                apply_all_migrations(first)
                artifact_id = enqueue_candidate(first, SAMPLE_ARTIFACT)
                stale_revision = get_item(second, artifact_id).revision

                decide(
                    first,
                    artifact_id,
                    "approved",
                    reviewer_identity="first-reviewer",
                    expected_revision=stale_revision,
                )
                with self.assertRaises(StaleReviewDecisionError):
                    decide(
                        second,
                        artifact_id,
                        "rejected",
                        reviewer_identity="second-reviewer",
                        expected_revision=stale_revision,
                    )
            finally:
                first.close()
                second.close()

    def test_reviewer_and_corrected_summary_are_required(self) -> None:
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        with self.assertRaises(ReviewDecisionError):
            decide(
                self.conn,
                artifact_id,
                "approved",
                reviewer_identity=" ",
                expected_revision=0,
            )
        with self.assertRaises(ReviewDecisionError):
            decide(
                self.conn,
                artifact_id,
                "corrected",
                reviewer_identity="operator",
                expected_revision=0,
            )

    def test_reviewer_notes_reject_body_and_secret_shaped_audit_text(self) -> None:
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        sensitive = "authorization" + ": bearer not-for-audit"
        for notes in ("message body\nsecond line", sensitive, "x" * 513):
            with self.subTest(notes=notes), self.assertRaises(ReviewDecisionError):
                decide(
                    self.conn,
                    artifact_id,
                    "approved",
                    reviewer_notes=notes,
                    reviewer_identity="operator",
                    expected_revision=0,
                )
        self.assertEqual(get_review_history(self.conn, artifact_id), [])

    def test_mutations_reject_active_caller_transactions(self) -> None:
        self.conn.execute("CREATE TABLE caller_state (value TEXT NOT NULL)")
        self.conn.commit()
        self.conn.execute("INSERT INTO caller_state (value) VALUES ('uncommitted')")

        with self.assertRaisesRegex(ReviewDecisionError, "active caller transaction"):
            enqueue_candidate(self.conn, SAMPLE_ARTIFACT)

        self.conn.rollback()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM caller_state").fetchone()[0], 0)
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        self.conn.execute("INSERT INTO caller_state (value) VALUES ('uncommitted')")
        with self.assertRaisesRegex(ReviewDecisionError, "active caller transaction"):
            decide(
                self.conn,
                artifact_id,
                "approved",
                reviewer_identity="operator",
                expected_revision=0,
            )
        self.conn.rollback()
        self.assertEqual(get_item(self.conn, artifact_id).review_status, "candidate")
        self.assertEqual(get_review_history(self.conn, artifact_id), [])

    def test_get_queue_filters_current_status(self) -> None:
        approved_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        pending_id = enqueue_candidate(
            self.conn,
            {**SAMPLE_ARTIFACT, "artifact_id": "pending-2"},
        )
        decide(
            self.conn,
            approved_id,
            "approved",
            reviewer_identity="operator",
            expected_revision=0,
        )

        ids = {item.artifact_id for item in get_queue(self.conn, status="candidate")}
        self.assertIn(pending_id, ids)
        self.assertNotIn(approved_id, ids)

    def test_get_item_returns_none_for_missing(self) -> None:
        self.assertIsNone(get_item(self.conn, "does-not-exist"))

    def test_decide_raises_key_error_for_missing(self) -> None:
        with self.assertRaises(KeyError):
            decide(
                self.conn,
                "no-such-id",
                "approved",
                reviewer_identity="operator",
                expected_revision=0,
            )


class LegacyQueueMigrationTests(unittest.TestCase):
    def test_legacy_evidence_and_decision_are_backfilled_once(self) -> None:
        connection = connect_sqlite()
        try:
            for filename in (
                "001_metadata_schema_v0.sql",
                "002_attachment_metadata.sql",
                "003_cache_and_queue.sql",
            ):
                migration = (
                    resources.files("mailplus_intelligence")
                    .joinpath("migrations")
                    .joinpath(filename)
                )
                connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                """
                INSERT INTO promotion_queue (
                  artifact_id, artifact_type, source_locators, source_thread_key,
                  summary, confidence, provenance, review_status,
                  reviewer_notes, queued_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-approved",
                    "obligation",
                    json.dumps(["fixture-export-legacy"]),
                    "thread-legacy",
                    "Legacy summary",
                    "medium",
                    json.dumps(["subject", "fixture-export-legacy"]),
                    "approved",
                    "Legacy approval",
                    "2026-01-01T10:00:00Z",
                    "2026-01-01T11:00:00Z",
                ),
            )
            connection.commit()

            apply_all_migrations(connection)
            apply_all_migrations(connection)

            item = get_item(connection, "legacy-approved")
            history = get_review_history(connection, "legacy-approved")
            self.assertEqual(current_schema_version(connection), 6)
            self.assertEqual(item.evidence_refs, ["subject", "fixture-export-legacy"])
            self.assertEqual(item.source_message_ids, [])
            self.assertEqual(item.provenance, "legacy")
            self.assertEqual(item.extractor_version, "legacy-unknown")
            self.assertEqual(item.revision, 1)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].event_type, "review.legacy_backfill")
            self.assertEqual(history[0].reviewer_identity, "legacy-migration")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
