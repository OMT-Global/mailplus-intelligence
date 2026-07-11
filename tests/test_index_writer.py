"""Tests for index writer and search (issues #2, #4, #73)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.index_writer import search_messages, write_index_records
from mailplus_intelligence.mapper import map_fixture_messages
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite


class IndexWriterTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        result = map_fixture_messages(corpus.messages)
        self.records = result.records
        self.write_result = write_index_records(self.conn, result.records)

    def tearDown(self):
        self.conn.close()

    def test_inserts_all_fixture_records(self):
        self.assertGreater(self.write_result.inserted, 0)
        self.assertEqual(self.write_result.updated, 0)
        self.assertEqual(self.write_result.unchanged, 0)
        self.assertEqual(self.write_result.failed, 0)
        self.assertEqual(len(self.write_result.errors), 0)

    def test_idempotent_second_write_skips(self):
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        result = map_fixture_messages(corpus.messages)
        second = write_index_records(self.conn, result.records)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.unchanged, len(result.records))
        self.assertEqual(second.skipped, second.unchanged)

    def test_changed_idempotent_record_is_updated(self):
        changed = replace(self.records[0], subject="Changed normalized subject")

        result = write_index_records(self.conn, (changed,))

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.unchanged, 0)
        row = self.conn.execute(
            "SELECT subject FROM messages WHERE locator_export_id = ?",
            (changed.locator_export_id,),
        ).fetchone()
        self.assertEqual(row["subject"], "Changed normalized subject")

    def test_unrelated_unique_constraint_is_failed_not_unchanged(self):
        existing = self.records[0]
        conflicting = replace(
            self.records[1],
            fixture_id="conflicting-mailbox-uid",
            mailbox=existing.mailbox,
            folder_path=existing.folder_path,
            locator_account=existing.locator_account,
            locator_mailbox=existing.locator_mailbox,
            locator_folder=existing.locator_folder,
            locator_uid=existing.locator_uid,
            locator_export_id="different-idempotency-identity",
        )

        result = write_index_records(self.conn, (conflicting,))

        self.assertEqual(result.unchanged, 0)
        self.assertEqual(result.failed, 1)
        self.assertIn("different locator_export_id", result.errors[0])

    def test_child_failure_rolls_back_parent_and_retry_repairs(self):
        connection = connect_sqlite()
        try:
            apply_all_migrations(connection)
            record = next(item for item in self.records if item.attachments)
            connection.executescript(
                """
                CREATE TRIGGER force_attachment_failure
                BEFORE INSERT ON attachments
                BEGIN
                  SELECT RAISE(ABORT, 'forced child failure');
                END;
                """
            )

            failed = write_index_records(connection, (record,))

            self.assertEqual(failed.failed, 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM message_participants"
                ).fetchone()[0],
                0,
            )
            connection.execute("DROP TRIGGER force_attachment_failure")
            connection.commit()

            retried = write_index_records(connection, (record,))

            self.assertEqual(retried.inserted, 1)
            self.assertEqual(retried.failed, 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                1,
            )
        finally:
            connection.close()

    def test_retry_repairs_a_preexisting_partial_record(self):
        connection = connect_sqlite()
        try:
            apply_all_migrations(connection)
            record = next(item for item in self.records if item.attachments)
            write_index_records(connection, (record,))
            message_row = connection.execute(
                "SELECT id FROM messages WHERE locator_export_id = ?",
                (record.locator_export_id,),
            ).fetchone()
            connection.execute(
                "DELETE FROM attachments WHERE message_id = ?",
                (message_row["id"],),
            )
            connection.commit()

            retried = write_index_records(connection, (record,))

            self.assertEqual(retried.updated, 1)
            self.assertEqual(retried.unchanged, 0)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM attachments WHERE message_id = ?",
                    (message_row["id"],),
                ).fetchone()[0],
                len(record.attachments),
            )
        finally:
            connection.close()

    def test_invalid_attachment_is_rejected_before_parent_mutation(self):
        connection = connect_sqlite()
        try:
            apply_all_migrations(connection)
            record = next(item for item in self.records if item.attachments)
            invalid_attachment = replace(record.attachments[0], size_bytes=-1)
            invalid = replace(
                record,
                attachments=(invalid_attachment,) + record.attachments[1:],
            )

            result = write_index_records(connection, (invalid,))

            self.assertEqual(result.failed, 1)
            self.assertIn("size_bytes must be non-negative", result.errors[0])
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM mailboxes").fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_search_by_sender(self):
        results = search_messages(self.conn, sender="alice@example.test")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("locator_export_id", r)

    def test_search_by_subject_keyword(self):
        results = search_messages(self.conn, subject_keyword="Atlas")
        self.assertGreater(len(results), 0)

    def test_search_by_folder(self):
        results = search_messages(self.conn, folder="Legal")
        self.assertGreater(len(results), 0)

    def test_search_by_has_attachments(self):
        with_att = search_messages(self.conn, has_attachments=True)
        without_att = search_messages(self.conn, has_attachments=False)
        self.assertGreater(len(with_att), 0)
        self.assertGreater(len(without_att), 0)

    def test_search_by_thread(self):
        results = search_messages(self.conn, thread_key="thread-a")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r["thread_key"], "thread-a")

    def test_search_attachment_mime_type(self):
        results = search_messages(self.conn, attachment_mime_type="application/pdf")
        self.assertGreater(len(results), 0)

    def test_search_attachment_name_contains(self):
        results = search_messages(self.conn, attachment_name_contains="atlas-plan")
        self.assertGreater(len(results), 0)

    def test_search_returns_locators(self):
        results = search_messages(self.conn, subject_keyword="Atlas")
        for r in results:
            self.assertIn("locator_export_id", r)
            self.assertIn("locator_uid", r)

    def test_search_empty_returns_all(self):
        results = search_messages(self.conn, limit=100)
        self.assertGreater(len(results), 0)


if __name__ == "__main__":
    unittest.main()
