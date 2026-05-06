from __future__ import annotations

import unittest

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.mapper import map_fixture_messages


class FixtureMapperTests(unittest.TestCase):
    def test_maps_fixture_records_without_raw_body_fields(self) -> None:
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        result = map_fixture_messages(corpus.messages)

        self.assertGreaterEqual(len(result.records), 7)
        first = result.records[0]
        self.assertEqual(first.message_id, "<thread-a-001@example.test>")
        self.assertEqual(first.sender, "alice@example.test")
        self.assertEqual(first.recipients, ("operator@example.test",))
        self.assertEqual(first.locator_export_id, "fixture-export-001")
        self.assertFalse(hasattr(first, "body"))
        self.assertFalse(hasattr(first, "raw_body"))

    def test_reports_duplicate_message_ids(self) -> None:
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        result = map_fixture_messages(corpus.messages)

        duplicate_issues = [
            issue for issue in result.issues if issue.code == "duplicate_message_id"
        ]
        self.assertEqual(len(duplicate_issues), 1)
        self.assertEqual(duplicate_issues[0].fixture_id, "msg-005-duplicate")

    def test_ignores_malformed_optional_references(self) -> None:
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        result = map_fixture_messages(corpus.messages)
        malformed = next(record for record in result.records if record.fixture_id == "msg-006-malformed")

        self.assertEqual(malformed.references, ())
        self.assertIsNone(malformed.in_reply_to)
        self.assertTrue(any(issue.code == "malformed_reference" for issue in result.issues))

    def test_treats_null_references_as_malformed_optional_value(self) -> None:
        message = {
            "fixture_id": "msg-null-references",
            "message_id": "<null-references@example.test>",
            "subject": "Null references",
            "from": "alice@example.test",
            "to": ["operator@example.test"],
            "date": "2026-01-01T00:00:00Z",
            "mailbox": "operator@example.test",
            "folder": "Inbox",
            "locator": {"uid": "1"},
            "references": None,
        }

        result = map_fixture_messages([message])

        self.assertEqual(result.records[0].references, ())
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].code, "malformed_reference")
        self.assertEqual(result.issues[0].fixture_id, "msg-null-references")

    def test_treats_scalar_references_as_malformed_optional_value(self) -> None:
        message = {
            "fixture_id": "msg-scalar-references",
            "message_id": "<scalar-references@example.test>",
            "subject": "Scalar references",
            "from": "alice@example.test",
            "to": ["operator@example.test"],
            "date": "2026-01-01T00:00:00Z",
            "mailbox": "operator@example.test",
            "folder": "Inbox",
            "locator": {"uid": "2"},
            "references": "<not-an-array@example.test>",
        }

        result = map_fixture_messages([message])

        self.assertEqual(result.records[0].references, ())
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].code, "malformed_reference")
        self.assertEqual(result.issues[0].fixture_id, "msg-scalar-references")


if __name__ == "__main__":
    unittest.main()
