"""Tests for the incremental sync pipeline."""

from __future__ import annotations

import copy
import unittest

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.index_writer import write_index_records
from mailplus_intelligence.mapper import map_fixture_messages
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
        self.assertEqual(result.inserted, len(corpus.messages))
        self.assertEqual(result.unchanged, 0)
        self.assertFalse(result.committed)
        self.assertFalse(result.checkpoint_advanced)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            0,
        )
        self.assertIsNone(get_checkpoint(self.conn, "test-source"))

    def test_live_run_inserts_records(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("test-source", "v1", corpus.messages)
        result = run_sync_batch(self.conn, batch)
        self.assertTrue(result.success)
        self.assertGreater(result.inserted, 0)
        self.assertTrue(result.committed)
        self.assertTrue(result.checkpoint_advanced)

    def test_idempotent_second_run_skips_all(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("test-source", "v1", corpus.messages)
        run_sync_batch(self.conn, batch)
        result2 = run_sync_batch(self.conn, batch)
        self.assertTrue(result2.success)
        self.assertEqual(result2.inserted, 0)
        self.assertEqual(result2.unchanged, len(corpus.messages))
        self.assertEqual(result2.skipped, result2.unchanged)

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

    def test_dry_run_counts_match_apply_without_writing(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("parity-source", "cursor-parity", corpus.messages[:2])

        dry_run = run_sync_batch(self.conn, batch, dry_run=True)
        applied = run_sync_batch(self.conn, batch)

        self.assertEqual(
            (
                dry_run.inserted,
                dry_run.updated,
                dry_run.unchanged,
                dry_run.rejected,
                dry_run.failed,
            ),
            (
                applied.inserted,
                applied.updated,
                applied.unchanged,
                applied.rejected,
                applied.failed,
            ),
        )

    def test_dry_run_update_plan_matches_apply_and_preserves_existing_row(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        existing = copy.deepcopy(corpus.messages[0])
        write_index_records(self.conn, map_fixture_messages([existing]).records)
        changed = copy.deepcopy(existing)
        changed["subject"] = "Planned update"
        inserted = copy.deepcopy(corpus.messages[1])
        batch = SyncBatch(
            "update-parity-source",
            "cursor-update-parity",
            (changed, inserted),
        )

        dry_run = run_sync_batch(self.conn, batch, dry_run=True)
        stored_before_apply = self.conn.execute(
            "SELECT subject FROM messages WHERE locator_export_id = ?",
            (existing["locator"]["export_id"],),
        ).fetchone()["subject"]
        applied = run_sync_batch(self.conn, batch)

        self.assertEqual(dry_run.updated, 1)
        self.assertEqual(dry_run.inserted, 1)
        self.assertEqual(stored_before_apply, existing["subject"])
        self.assertEqual(
            (
                dry_run.inserted,
                dry_run.updated,
                dry_run.unchanged,
                dry_run.rejected,
                dry_run.failed,
            ),
            (
                applied.inserted,
                applied.updated,
                applied.unchanged,
                applied.rejected,
                applied.failed,
            ),
        )

    def test_dry_run_does_not_change_existing_checkpoint_attempt_time(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        applied = SyncBatch("dry-existing-source", "cursor-old", corpus.messages[:1])
        run_sync_batch(self.conn, applied)
        before = get_checkpoint(self.conn, "dry-existing-source")

        dry_run = SyncBatch("dry-existing-source", "cursor-new", corpus.messages[:1])
        result = run_sync_batch(self.conn, dry_run, dry_run=True)

        self.assertTrue(result.success)
        self.assertEqual(
            get_checkpoint(self.conn, "dry-existing-source"),
            before,
        )

    def test_fatal_mapper_reject_prevents_data_and_checkpoint(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        valid = copy.deepcopy(corpus.messages[0])
        rejected = copy.deepcopy(corpus.messages[1])
        del rejected["subject"]
        batch = SyncBatch("reject-source", "cursor-rejected", (valid, rejected))

        result = run_sync_batch(self.conn, batch)

        self.assertFalse(result.success)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.rejected, 1)
        self.assertEqual(result.accounted, 2)
        self.assertEqual(result.rejections[0].code, "missing_required")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            0,
        )
        self.assertIsNone(get_checkpoint(self.conn, "reject-source"))

    def test_partial_child_failure_rolls_back_batch_and_retry_succeeds(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        message = next(item for item in corpus.messages if item.get("attachments"))
        batch = SyncBatch("child-failure-source", "cursor-child", (message,))
        self.conn.executescript(
            """
            CREATE TRIGGER force_sync_attachment_failure
            BEFORE INSERT ON attachments
            BEGIN
              SELECT RAISE(ABORT, 'forced child failure');
            END;
            """
        )

        failed = run_sync_batch(self.conn, batch)

        self.assertFalse(failed.success)
        self.assertEqual(failed.failed, 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            0,
        )
        self.assertIsNone(get_checkpoint(self.conn, "child-failure-source"))
        self.conn.execute("DROP TRIGGER force_sync_attachment_failure")
        self.conn.commit()

        retried = run_sync_batch(self.conn, batch)

        self.assertTrue(retried.success)
        self.assertEqual(retried.inserted, 1)
        self.assertEqual(
            get_checkpoint(self.conn, "child-failure-source")["cursor"],
            "cursor-child",
        )

    def test_checkpoint_failure_rolls_back_data_changes(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        batch = SyncBatch("checkpoint-failure", "cursor-never-committed", corpus.messages[:1])
        self.conn.executescript(
            """
            CREATE TRIGGER force_checkpoint_failure
            BEFORE INSERT ON sync_checkpoints
            BEGIN
              SELECT RAISE(ABORT, 'forced checkpoint failure');
            END;
            """
        )

        result = run_sync_batch(self.conn, batch)

        self.assertFalse(result.success)
        self.assertFalse(result.committed)
        self.assertFalse(result.checkpoint_advanced)
        self.assertTrue(any("forced checkpoint failure" in error for error in result.write_errors))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            0,
        )
        self.assertIsNone(get_checkpoint(self.conn, "checkpoint-failure"))

    def test_checkpoint_update_failure_restores_prior_data_and_cursor(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        original = copy.deepcopy(corpus.messages[0])
        initial = SyncBatch("checkpoint-update", "cursor-old", (original,))
        run_sync_batch(self.conn, initial)
        changed = copy.deepcopy(original)
        changed["subject"] = "Subject that must roll back"
        self.conn.executescript(
            """
            CREATE TRIGGER force_checkpoint_update_failure
            BEFORE UPDATE OF cursor ON sync_checkpoints
            WHEN NEW.cursor = 'cursor-new'
            BEGIN
              SELECT RAISE(ABORT, 'forced checkpoint update failure');
            END;
            """
        )

        result = run_sync_batch(
            self.conn,
            SyncBatch("checkpoint-update", "cursor-new", (changed,)),
        )

        self.assertFalse(result.success)
        self.assertEqual(
            get_checkpoint(self.conn, "checkpoint-update")["cursor"],
            "cursor-old",
        )
        stored = self.conn.execute(
            "SELECT subject FROM messages WHERE locator_export_id = ?",
            (original["locator"]["export_id"],),
        ).fetchone()
        self.assertEqual(stored["subject"], original["subject"])

    def test_mixed_batch_accounts_for_every_input_without_advancing(self) -> None:
        corpus = load_metadata_fixture_corpus(FIXTURE_DIR)
        unchanged = copy.deepcopy(corpus.messages[0])
        seeded = map_fixture_messages([unchanged])
        write_index_records(self.conn, seeded.records)

        updated = copy.deepcopy(unchanged)
        updated["subject"] = "Updated subject"
        inserted = copy.deepcopy(corpus.messages[1])
        rejected = copy.deepcopy(corpus.messages[2])
        del rejected["subject"]
        failed = copy.deepcopy(corpus.messages[3])
        failed["locator"]["export_id"] = ""
        batch = SyncBatch(
            "mixed-source",
            "cursor-mixed",
            (unchanged, updated, inserted, rejected, failed),
        )

        result = run_sync_batch(self.conn, batch)

        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.unchanged, 1)
        self.assertEqual(result.rejected, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.accounted, len(batch.messages))
        self.assertFalse(result.success)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            1,
        )
        self.assertIsNone(get_checkpoint(self.conn, "mixed-source"))


if __name__ == "__main__":
    unittest.main()
