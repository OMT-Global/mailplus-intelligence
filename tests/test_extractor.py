"""Tests for the deterministic extractor pipeline."""

from __future__ import annotations

import unittest

from mailplus_intelligence.extractor import extract_from_corpus, extract_from_thread
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.threading import reconstruct_fixture_threads


FIXTURE_DIR = "fixtures/mailplus_metadata"


class ExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        self.threads = reconstruct_fixture_threads(corpus.messages)
        self.messages = list(corpus.messages)

    def test_extract_from_corpus_returns_candidates(self) -> None:
        candidates = extract_from_corpus(self.threads, self.messages)
        self.assertGreater(len(candidates), 0)

    def test_all_candidates_have_required_fields(self) -> None:
        candidates = extract_from_corpus(self.threads, self.messages)
        for c in candidates:
            self.assertIsNotNone(c.artifact_id)
            self.assertIn(c.artifact_type, {"thread_summary", "obligation", "event"})
            self.assertIn(c.review_status, {"candidate", "review_needed"})
            self.assertEqual(c.provenance, "deterministic")

    def test_thread_summary_produced_for_extraction_lane(self) -> None:
        candidates = extract_from_corpus(self.threads, self.messages)
        types = {c.artifact_type for c in candidates}
        self.assertIn("thread_summary", types)

    def test_noise_thread_suppressed(self) -> None:
        messages = [
            {
                "fixture_id": "msg-noise-x",
                "message_id": "<noise-x@example.test>",
                "subject": "Daily digest newsletter",
                "from": "no-reply@newsletter.example.com",
                "to": ["operator@example.test"],
                "date": "2026-01-01T00:00:00Z",
                "mailbox": "operator@example.test",
                "folder": "Inbox",
                "locator": {"uid": "77", "account": "fixture-account"},
                "attachments": [],
            }
        ]
        threads = reconstruct_fixture_threads(messages)
        for thread in threads:
            candidates = extract_from_thread(thread, messages)
            self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
