"""Privacy-first tests for the operator-selected transient source boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.source_fetch import (
    FixtureSourceBackend,
    LiveSourceBackend,
    SourceFetchCredentialGated,
    SourceFetchAmbiguous,
    SourceFetchBackendUnavailable,
    SourceFetchMoved,
    SourceFetchNotFound,
    SourceFetchPolicyError,
    SourceFetchRequest,
    SourceLocator,
    TransientSourceDisposed,
    extract_minimized_source,
    fetch_selected_source,
)
from mailplus_intelligence.sqlite import connect_sqlite


SENTINEL = "UNIQUE_TRANSIENT_SENTINEL_8492"


class SourceFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.locator = SourceLocator(
            export_id="fixture-source-001",
            uid="501",
            account="fixture@example.com",
            mailbox="fixture@example.com",
            folder_path="Inbox",
            message_id="<fixture-source-001@example.com>",
            thread_key="fixture-thread-001",
        )
        self.request = SourceFetchRequest(self.locator, purpose="extraction")
        self.body = (
            "I will send the revised plan tomorrow.\n"
            f"token={SENTINEL}\n"
            "https://example.com/reset?token=never-store\n"
            "-- \nExample Sender\nOn yesterday, Example Person wrote:\n> old quoted history"
        )
        self.backend = FixtureSourceBackend({self.locator: self.body})

    def test_exact_operator_selected_fetch_is_transient_and_disposed(self) -> None:
        with fetch_selected_source(self.request, self.backend) as source:
            self.assertEqual(self.backend.requests, [self.locator])
            self.assertIn(SENTINEL, source.text)
        with self.assertRaises(TransientSourceDisposed):
            _ = source.text
        self.assertNotIn(SENTINEL, repr(source))

    def test_minimization_redacts_secrets_links_signatures_and_history(self) -> None:
        with fetch_selected_source(self.request, self.backend) as source:
            minimized = source.minimized_text
            self.assertNotIn(SENTINEL, minimized)
            self.assertNotIn(SENTINEL, minimized)
            self.assertNotIn("reset?", minimized)
            self.assertNotIn("Example Sender", minimized)
            self.assertNotIn("quoted history", minimized)
            self.assertIn("I will send the revised plan tomorrow.", minimized)

    def test_missing_and_moved_locators_are_typed(self) -> None:
        unknown = SourceLocator("fixture-source-404", "404", "fixture@example.com", "fixture@example.com", "Inbox")
        with self.assertRaises(SourceFetchNotFound):
            fetch_selected_source(SourceFetchRequest(unknown, purpose="review"), self.backend)
        moved = SourceLocator("fixture-source-001", "999", "fixture@example.com", "fixture@example.com", "Archive")
        with self.assertRaises(SourceFetchMoved):
            fetch_selected_source(SourceFetchRequest(moved, purpose="review"), self.backend)

    def test_purpose_and_live_backend_fail_closed(self) -> None:
        with self.assertRaises(SourceFetchPolicyError):
            SourceFetchRequest(self.locator, purpose="automatic-reminder")
        with self.assertRaises(SourceFetchAmbiguous):
            SourceLocator("", "501", "fixture@example.com", "fixture@example.com", "Inbox")
        with self.assertRaises(SourceFetchCredentialGated):
            fetch_selected_source(self.request, LiveSourceBackend())
        with self.assertRaises(SourceFetchBackendUnavailable):
            fetch_selected_source(self.request, FixtureSourceBackend({}, unavailable=True))

    def test_extraction_keeps_only_locator_and_hash_in_durable_surfaces(self) -> None:
        with fetch_selected_source(self.request, self.backend) as source:
            candidates = extract_minimized_source(source)
        self.assertEqual(len(candidates), 1)
        payload = candidates[0].to_dict()
        self.assertEqual(payload["review_status"], "review_needed")
        self.assertTrue(payload["evidence_refs"][0].startswith("sha256:"))
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(SENTINEL, serialized)

        conn = connect_sqlite(":memory:")
        self.addCleanup(conn.close)
        apply_all_migrations(conn)
        self.assertNotIn(SENTINEL, "\n".join(conn.iterdump()))
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            report.write_text(serialized, encoding="utf-8")
            self.assertNotIn(SENTINEL, report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
