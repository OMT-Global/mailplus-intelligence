"""Tests for index writer and search (issues #2, #4, #73)."""

from __future__ import annotations

import unittest

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
        self.write_result = write_index_records(self.conn, result.records)

    def tearDown(self):
        self.conn.close()

    def test_inserts_all_fixture_records(self):
        self.assertGreater(self.write_result.inserted, 0)
        self.assertEqual(len(self.write_result.errors), 0)

    def test_idempotent_second_write_skips(self):
        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        result = map_fixture_messages(corpus.messages)
        second = write_index_records(self.conn, result.records)
        self.assertEqual(second.inserted, 0)
        self.assertGreater(second.skipped, 0)

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
