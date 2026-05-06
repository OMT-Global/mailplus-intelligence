from __future__ import annotations

import unittest
from pathlib import Path

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "mailplus_metadata"


class MetadataFixtureCorpusTests(unittest.TestCase):
    def test_fixture_corpus_loads_with_expected_thread_outputs(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)

        self.assertEqual(corpus.version, 1)
        self.assertGreaterEqual(len(corpus.messages), 7)
        self.assertEqual(len(corpus.expected_threads["threads"]), 4)

    def test_fixture_corpus_is_metadata_only_and_has_locators(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)

        for message in corpus.messages:
            self.assertNotIn("body", message)
            self.assertNotIn("raw", message)
            self.assertIn("locator", message)
            self.assertEqual(message["locator"]["account"], "fixture-account")

    def test_fixture_corpus_covers_required_edge_cases(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        fixture_ids = {message["fixture_id"] for message in corpus.messages}

        self.assertIn("msg-003", fixture_ids)
        self.assertIn("msg-004", fixture_ids)
        self.assertIn("msg-005-duplicate", fixture_ids)
        self.assertIn("msg-006-malformed", fixture_ids)

        duplicate_message_ids = [
            message["message_id"]
            for message in corpus.messages
            if message["message_id"] == "<duplicate-001@example.test>"
        ]
        self.assertEqual(len(duplicate_message_ids), 2)

        attachment_names = {
            attachment["filename"]
            for message in corpus.messages
            for attachment in message["attachments"]
        }
        self.assertIn("atlas-plan.txt", attachment_names)
        self.assertIn("intake.pdf", attachment_names)


if __name__ == "__main__":
    unittest.main()
