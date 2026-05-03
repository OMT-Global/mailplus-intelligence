from __future__ import annotations

import unittest

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.threading import normalize_subject, reconstruct_fixture_threads


class ThreadReconstructionTests(unittest.TestCase):
    def test_reconstructs_expected_fixture_threads(self) -> None:
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        threads = reconstruct_fixture_threads(corpus.messages)
        actual = {thread.thread_id: thread for thread in threads}

        self.assertEqual(
            actual["thread-a"].message_fixture_ids,
            ("msg-001", "msg-002", "msg-003"),
        )
        self.assertEqual(actual["thread-a"].confidence, "high")
        self.assertIn("references", actual["thread-a"].basis)
        self.assertIn("in-reply-to", actual["thread-a"].basis)

    def test_duplicate_message_ids_stay_together(self) -> None:
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        actual = {thread.thread_id: thread for thread in reconstruct_fixture_threads(corpus.messages)}

        self.assertEqual(
            actual["thread-duplicate"].message_fixture_ids,
            ("msg-005-original", "msg-005-duplicate"),
        )
        self.assertIn("duplicate-message-id", actual["thread-duplicate"].basis)

    def test_malformed_optional_headers_are_low_confidence(self) -> None:
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        actual = {thread.thread_id: thread for thread in reconstruct_fixture_threads(corpus.messages)}

        self.assertEqual(actual["thread-malformed"].confidence, "low")
        self.assertIn("malformed-optional-headers", actual["thread-malformed"].basis)

    def test_subject_normalization_is_conservative(self) -> None:
        self.assertEqual(normalize_subject("Re: Fwd: Project Atlas kickoff"), "project atlas kickoff")


if __name__ == "__main__":
    unittest.main()
