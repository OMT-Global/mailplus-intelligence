"""Tests for the incremental sync pipeline."""

from __future__ import annotations

import unittest

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite
from mailplus_intelligence.sync import SyncBatch, get_checkpoint, run_sync_batch


FIXTURE_DIR = "fixtures/mailplus_metadata"


class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect_sqlite(":memory:")
        apply_all_migrations(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_dry_run_inserts_nothing(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("test-source", "v1", corpus.messages)
        result = run_sync_batch(self.conn, batch, dry_run=True)
        self.assertTrue(result.success)
        self.assertEqual(result.inserted, 0)
        self.assertGreater(result.skipped, 0)

    def test_live_run_inserts_records(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("test-source", "v1", corpus.messages)
        result = run_sync_batch(self.conn, batch)
        self.assertTrue(result.success)
        self.assertGreater(result.inserted, 0)

    def test_idempotent_second_run_skips_all(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("test-source", "v1", corpus.messages)
        run_sync_batch(self.conn, batch)
        result2 = run_sync_batch(self.conn, batch)
        self.assertTrue(result2.success)
        self.assertEqual(result2.inserted, 0)

    def test_checkpoint_updated_on_success(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("test-source", "cursor-abc", corpus.messages)
        run_sync_batch(self.conn, batch)
        cp = get_checkpoint(self.conn, "test-source")
        self.assertIsNotNone(cp)
        self.assertEqual(cp["cursor"], "cursor-abc")
        self.assertIsNotNone(cp["last_success_at"])

    def test_checkpoint_none_before_any_sync(self) -> None:
        cp = get_checkpoint(self.conn, "never-run")
        self.assertIsNone(cp)


if __name__ == "__main__":
    unittest.main()
