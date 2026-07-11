"""Tests for validated, idempotent dry-run promotion exports."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mailplus_intelligence.exporters import (
    ExportEligibilityError,
    export_approved_candidates,
)
from mailplus_intelligence.queue import (
    ReviewDecisionError,
    decide,
    enqueue_candidate,
    get_item,
    get_outbox,
    get_queue,
    mark_outbox_exported,
    mark_outbox_failed,
    mark_outbox_rolled_back,
    reserve_outbox,
)
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite


def _artifact(artifact_id: str, artifact_type: str = "obligation") -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "source_thread_key": "thread-a",
        "source_message_ids": [f"<{artifact_id}@example.test>"],
        "source_locators": [f"fixture-export-{artifact_id}"],
        "evidence_refs": ["subject"],
        "summary": f"Summary for {artifact_id}.",
        "confidence": "high",
        "review_status": "candidate",
        "provenance": "deterministic",
        "extractor_version": "metadata-extractor-v1",
        "model_version": None,
        "rule_version": "metadata-rules-v1",
        "created_at": "2026-01-10T10:00:00Z",
    }


class DryRunExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _review(
        self,
        artifact_id: str,
        decision: str,
        *,
        expected_revision: int = 0,
        corrected_summary: str | None = None,
        notes: str | None = None,
    ) -> None:
        decide(
            self.conn,
            artifact_id,
            decision,
            reviewer_notes=notes,
            corrected_summary=corrected_summary,
            reviewer_identity="reviewer@example.test",
            expected_revision=expected_revision,
        )

    def test_exports_approved_and_corrected_only(self) -> None:
        for artifact_id in ("approved", "corrected", "rejected"):
            enqueue_candidate(self.conn, _artifact(artifact_id))
        self._review("approved", "approved")
        self._review("corrected", "corrected", corrected_summary="Corrected summary.")
        self._review("rejected", "rejected")

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates(
                get_queue(self.conn),
                tmp,
                connection=self.conn,
            )

        self.assertEqual({artifact.artifact_id for artifact in artifacts}, {"approved", "corrected"})

    def test_artifact_and_manifest_include_complete_provenance(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved", notes="Confirmed")

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates(
                [get_item(self.conn, "approved")],
                tmp,
                connection=self.conn,
            )
            payload = json.loads(artifacts[0].content)
            manifest = json.loads((Path(tmp) / "export-manifest.json").read_text())
            self.assertTrue((Path(tmp) / artifacts[0].target_path).exists())

        self.assertEqual(payload["source_message_ids"], ["<approved@example.test>"])
        self.assertEqual(payload["evidence_refs"], ["subject"])
        self.assertEqual(payload["provenance"], "deterministic")
        self.assertEqual(payload["extractor_version"], "metadata-extractor-v1")
        self.assertEqual(payload["rule_version"], "metadata-rules-v1")
        self.assertEqual(payload["original_summary"], "Summary for approved.")
        self.assertEqual(payload["reviewer_identity"], "reviewer@example.test")
        self.assertNotIn("reviewer_notes", payload)
        self.assertEqual(manifest["artifact_count"], 1)
        self.assertEqual(manifest["artifacts"][0]["artifact_revision"], 1)
        self.assertTrue(manifest["artifacts"][0]["outbox_id"])
        self.assertTrue(manifest["artifacts"][0]["idempotency_key"])

    def test_corrected_summary_is_exported_without_mutating_original(self) -> None:
        enqueue_candidate(self.conn, _artifact("corrected", "thread_summary"))
        self._review(
            "corrected",
            "corrected",
            corrected_summary="Corrected: Atlas launched with Alice.",
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates(
                [get_item(self.conn, "corrected")],
                tmp,
                connection=self.conn,
            )

        self.assertIn("Corrected: Atlas", artifacts[0].content)
        self.assertEqual(get_item(self.conn, "corrected").summary, "Summary for corrected.")

    def test_repeated_export_reuses_one_outbox_identity(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")
        item = get_item(self.conn, "approved")

        with tempfile.TemporaryDirectory() as tmp:
            first = export_approved_candidates([item], tmp, connection=self.conn)[0]
            second = export_approved_candidates([item], tmp, connection=self.conn)[0]

        self.assertEqual(first.outbox_id, second.outbox_id)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        count = self.conn.execute("SELECT COUNT(*) FROM export_outbox").fetchone()[0]
        self.assertEqual(count, 1)

    def test_exported_target_mismatch_fails_without_overwriting(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")
        item = get_item(self.conn, "approved")

        with tempfile.TemporaryDirectory() as tmp:
            exported = export_approved_candidates([item], tmp, connection=self.conn)[0]
            target = Path(tmp) / exported.target_path
            target.write_text("external change", encoding="utf-8")

            with self.assertRaisesRegex(ExportEligibilityError, "missing or changed"):
                export_approved_candidates([item], tmp, connection=self.conn)

            self.assertEqual(target.read_text(encoding="utf-8"), "external change")
            self.assertEqual(get_outbox(self.conn, exported.outbox_id).state, "exported")

    def test_atomic_write_failure_leaves_no_partial_target_and_marks_failed(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "mailplus_intelligence.exporters.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "synthetic replace failure"):
                export_approved_candidates(
                    [get_item(self.conn, "approved")],
                    tmp,
                    connection=self.conn,
                )
            outbox = self.conn.execute(
                "SELECT * FROM export_outbox WHERE artifact_id = 'approved'"
            ).fetchone()
            self.assertEqual(outbox["state"], "failed")
            self.assertFalse(any(path.is_file() for path in Path(tmp).rglob("*")))

    def test_export_rejects_queue_snapshot_that_differs_from_review_event(self) -> None:
        enqueue_candidate(self.conn, _artifact("corrected"))
        self._review(
            "corrected",
            "corrected",
            corrected_summary="Reviewed correction.",
        )
        self.conn.execute("DROP TRIGGER promotion_queue_review_snapshot_consistent")
        self.conn.execute(
            "UPDATE promotion_queue SET corrected_summary = 'unreviewed mutation' "
            "WHERE artifact_id = 'corrected'"
        )
        self.conn.commit()

        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            ExportEligibilityError,
            "matching latest review decision",
        ):
            export_approved_candidates(
                [get_item(self.conn, "corrected")],
                tmp,
                connection=self.conn,
            )

    def test_stale_approved_snapshot_cannot_export(self) -> None:
        enqueue_candidate(self.conn, _artifact("stale"))
        self._review("stale", "approved")
        stale_item = get_item(self.conn, "stale")
        self._review(
            "stale",
            "corrected",
            expected_revision=1,
            corrected_summary="New correction.",
        )

        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ExportEligibilityError):
            export_approved_candidates([stale_item], tmp, connection=self.conn)

    def test_incomplete_legacy_provenance_cannot_export(self) -> None:
        self.conn.execute(
            """
            INSERT INTO promotion_queue (
              artifact_id, artifact_type, source_message_ids, source_locators,
              evidence_refs, source_thread_key, summary, confidence, provenance,
              extractor_version, artifact_created_at, initial_review_status,
              review_status, revision, latest_review_event_id, reviewer_identity,
              queued_at, decided_at
            ) VALUES (
              'legacy', 'obligation', '[]', '["legacy-locator"]', '["subject"]',
              'legacy-thread', 'Legacy', 'medium', 'legacy', 'legacy-unknown',
              '2026-01-01T00:00:00Z', 'candidate', 'approved', 1,
              'legacy-event', 'legacy-migration', '2026-01-01T00:00:00Z',
              '2026-01-01T01:00:00Z'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO review_events (
              event_id, artifact_id, artifact_revision, event_type, prior_status,
              new_status, reviewer_identity, occurred_at
            ) VALUES (
              'legacy-event', 'legacy', 1, 'review.legacy_backfill', 'candidate',
              'approved', 'legacy-migration', '2026-01-01T01:00:00Z'
            )
            """
        )
        self.conn.commit()

        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ExportEligibilityError):
            export_approved_candidates(
                [get_item(self.conn, "legacy")],
                tmp,
                connection=self.conn,
            )

    def test_rollback_decision_updates_and_completes_outbox(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")
        with tempfile.TemporaryDirectory() as tmp:
            artifact = export_approved_candidates(
                [get_item(self.conn, "approved")],
                tmp,
                connection=self.conn,
            )[0]

        self._review(
            "approved",
            "rollback_needed",
            expected_revision=1,
            notes="The source decision was superseded.",
        )
        outbox = get_outbox(self.conn, artifact.outbox_id)
        self.assertEqual(outbox.state, "rollback_needed")
        self.assertEqual(outbox.rollback_note, "The source decision was superseded.")

        outbox = mark_outbox_rolled_back(self.conn, artifact.outbox_id)
        self.assertEqual(outbox.state, "rolled_back")
        self.assertIsNotNone(outbox.rolled_back_at)

    def test_newer_correction_blocks_a_planned_older_revision(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")
        item = get_item(self.conn, "approved")
        outbox = reserve_outbox(
            self.conn,
            item,
            export_type="obligation_proposal",
            target_key="memory/obligations/approved.json",
            content_hash="content-hash",
            rollback_note="Delete the dry-run file.",
        )

        self._review(
            "approved",
            "corrected",
            expected_revision=1,
            corrected_summary="Superseding correction.",
        )

        self.assertEqual(get_outbox(self.conn, outbox.outbox_id).state, "rollback_needed")
        with self.assertRaises(ReviewDecisionError):
            mark_outbox_exported(self.conn, outbox.outbox_id)

        with tempfile.TemporaryDirectory() as tmp:
            corrected = export_approved_candidates(
                [get_item(self.conn, "approved")],
                tmp,
                connection=self.conn,
            )[0]
        self.assertNotEqual(corrected.target_path, outbox.target_key)
        self.assertIn("-r2.json", corrected.target_path)

    def test_outbox_mutations_reject_active_caller_transactions(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")
        item = get_item(self.conn, "approved")
        self.conn.execute("CREATE TABLE caller_state (value TEXT NOT NULL)")
        self.conn.commit()
        self.conn.execute("INSERT INTO caller_state (value) VALUES ('uncommitted')")

        with self.assertRaisesRegex(ReviewDecisionError, "active caller transaction"):
            reserve_outbox(
                self.conn,
                item,
                export_type="obligation_proposal",
                target_key="memory/obligations/approved.json",
                content_hash="content-hash",
                rollback_note="Delete the dry-run file.",
            )
        self.conn.rollback()
        outbox = reserve_outbox(
            self.conn,
            item,
            export_type="obligation_proposal",
            target_key="memory/obligations/approved.json",
            content_hash="content-hash",
            rollback_note="Delete the dry-run file.",
        )
        self.conn.execute("INSERT INTO caller_state (value) VALUES ('uncommitted')")
        with self.assertRaisesRegex(ReviewDecisionError, "active caller transaction"):
            mark_outbox_exported(self.conn, outbox.outbox_id)
        self.conn.rollback()
        self.assertEqual(get_outbox(self.conn, outbox.outbox_id).state, "planned")

    def test_outbox_failure_rejects_payload_shaped_details(self) -> None:
        enqueue_candidate(self.conn, _artifact("approved"))
        self._review("approved", "approved")
        item = get_item(self.conn, "approved")
        outbox = reserve_outbox(
            self.conn,
            item,
            export_type="obligation_proposal",
            target_key="memory/obligations/approved.json",
            content_hash="content-hash",
            rollback_note="Delete the dry-run file.",
        )

        with self.assertRaisesRegex(ValueError, "privacy-safe reason code"):
            mark_outbox_failed(
                self.conn,
                outbox.outbox_id,
                failure_code="request failed with token=not-for-audit",
            )

    def test_live_mode_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
            export_approved_candidates([], tmp, connection=self.conn, dry_run=False)

    def test_empty_list_produces_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates([], tmp, connection=self.conn)
            manifest = json.loads((Path(tmp) / "export-manifest.json").read_text())

        self.assertEqual(artifacts, [])
        self.assertEqual(manifest["artifact_count"], 0)


if __name__ == "__main__":
    unittest.main()
