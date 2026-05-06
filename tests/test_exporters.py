"""Tests for dry-run promotion exporters (issue #36)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mailplus_intelligence.exporters import export_approved_candidates
from mailplus_intelligence.queue import QueueItem

APPROVED_OBLIGATION = QueueItem(
    artifact_id="test-obligation-001",
    artifact_type="obligation",
    source_locators=["fixture-export-001"],
    source_thread_key="thread-a",
    summary="Deliver Atlas plan by end of week.",
    confidence="high",
    provenance='["fixture-export-001"]',
    review_status="approved",
    reviewer_notes="Confirmed",
    corrected_summary=None,
    queued_at="2026-01-10T10:00:00Z",
    decided_at="2026-01-10T11:00:00Z",
)

CORRECTED_SUMMARY = QueueItem(
    artifact_id="test-thread-sum-001",
    artifact_type="thread_summary",
    source_locators=["fixture-export-001", "fixture-export-002"],
    source_thread_key="thread-a",
    summary="Original summary.",
    confidence="medium",
    provenance='["fixture-export-001"]',
    review_status="corrected",
    reviewer_notes=None,
    corrected_summary="Corrected: Atlas project kicked off with Alice.",
    queued_at="2026-01-10T10:00:00Z",
    decided_at="2026-01-10T11:30:00Z",
)

REJECTED_ITEM = QueueItem(
    artifact_id="test-rejected-001",
    artifact_type="decision",
    source_locators=["fixture-export-003"],
    source_thread_key="thread-b",
    summary="Should not be exported.",
    confidence="low",
    provenance="[]",
    review_status="rejected",
    reviewer_notes="False positive",
    corrected_summary=None,
    queued_at="2026-01-10T10:00:00Z",
    decided_at="2026-01-10T11:00:00Z",
)


class DryRunExporterTests(unittest.TestCase):
    def test_exports_approved_and_corrected_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates(
                [APPROVED_OBLIGATION, CORRECTED_SUMMARY, REJECTED_ITEM],
                tmp,
                dry_run=True,
            )
            ids = {a.artifact_id for a in artifacts}
            self.assertIn("test-obligation-001", ids)
            self.assertIn("test-thread-sum-001", ids)
            self.assertNotIn("test-rejected-001", ids)

    def test_artifact_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates(
                [APPROVED_OBLIGATION],
                tmp,
                dry_run=True,
            )
            for a in artifacts:
                path = Path(tmp) / a.target_path
                self.assertTrue(path.exists(), f"Expected file at {path}")

    def test_corrected_summary_used_in_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates([CORRECTED_SUMMARY], tmp, dry_run=True)
            self.assertEqual(len(artifacts), 1)
            self.assertIn("Corrected:", artifacts[0].content)

    def test_manifest_written_with_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            export_approved_candidates([APPROVED_OBLIGATION], tmp, dry_run=True)
            manifest = json.loads((Path(tmp) / "export-manifest.json").read_text())
            self.assertTrue(manifest["dry_run"])
            self.assertEqual(manifest["artifact_count"], 1)
            self.assertEqual(manifest["artifacts"][0]["artifact_id"], "test-obligation-001")
            self.assertEqual(manifest["artifacts"][0]["locators"], ["fixture-export-001"])

    def test_rollback_note_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates([APPROVED_OBLIGATION], tmp, dry_run=True)
            self.assertIsNotNone(artifacts[0].rollback_note)

    def test_live_mode_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                export_approved_candidates([APPROVED_OBLIGATION], tmp, dry_run=False)

    def test_empty_list_produces_empty_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = export_approved_candidates([], tmp, dry_run=True)
            self.assertEqual(len(artifacts), 0)
            manifest = json.loads((Path(tmp) / "export-manifest.json").read_text())
            self.assertEqual(manifest["artifact_count"], 0)


if __name__ == "__main__":
    unittest.main()
