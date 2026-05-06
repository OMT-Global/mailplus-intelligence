"""Tests for promotion review queue (issue #35)."""

from __future__ import annotations

import unittest

from mailplus_intelligence.queue import decide, enqueue_candidate, get_item, get_queue
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite

SAMPLE_ARTIFACT = {
    "artifact_type": "obligation",
    "source_thread_key": "thread-a",
    "source_locators": ["fixture-export-001"],
    "evidence_refs": ["fixture-export-001"],
    "summary": "Alice committed to delivering the Atlas plan by end of week.",
    "confidence": "high",
    "review_status": "candidate",
}


class PromotionQueueTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_enqueue_returns_artifact_id(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        self.assertIsInstance(artifact_id, str)
        self.assertTrue(len(artifact_id) > 0)

    def test_enqueued_item_has_candidate_status(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        item = get_item(self.conn, artifact_id)
        self.assertIsNotNone(item)
        self.assertEqual(item.review_status, "candidate")
        self.assertEqual(item.summary, SAMPLE_ARTIFACT["summary"])

    def test_approve_changes_status(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        decide(self.conn, artifact_id, "approved", reviewer_notes="Looks good")
        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.review_status, "approved")
        self.assertEqual(item.reviewer_notes, "Looks good")
        self.assertIsNotNone(item.decided_at)

    def test_reject_changes_status(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        decide(self.conn, artifact_id, "rejected")
        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.review_status, "rejected")

    def test_defer_changes_status(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        decide(self.conn, artifact_id, "deferred")
        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.review_status, "deferred")

    def test_correct_preserves_original_and_stores_correction(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        decide(self.conn, artifact_id, "corrected", corrected_summary="Corrected summary text")
        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.review_status, "corrected")
        self.assertEqual(item.corrected_summary, "Corrected summary text")
        self.assertEqual(item.summary, SAMPLE_ARTIFACT["summary"])

    def test_get_queue_filters_by_status(self):
        a1 = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        a2 = enqueue_candidate(self.conn, {**SAMPLE_ARTIFACT, "artifact_id": "unique-2"})
        decide(self.conn, a1, "approved")
        items = get_queue(self.conn, status="candidate")
        ids = {i.artifact_id for i in items}
        self.assertIn(a2, ids)
        self.assertNotIn(a1, ids)

    def test_get_item_returns_none_for_missing(self):
        result = get_item(self.conn, "does-not-exist")
        self.assertIsNone(result)

    def test_decide_raises_key_error_for_missing(self):
        with self.assertRaises(KeyError):
            decide(self.conn, "no-such-id", "approved")

    def test_decide_raises_value_error_for_invalid_decision(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        with self.assertRaises(ValueError):
            decide(self.conn, artifact_id, "super_approve")

    def test_source_locators_round_trip(self):
        artifact_id = enqueue_candidate(self.conn, SAMPLE_ARTIFACT)
        item = get_item(self.conn, artifact_id)
        self.assertEqual(item.source_locators, ["fixture-export-001"])


if __name__ == "__main__":
    unittest.main()
