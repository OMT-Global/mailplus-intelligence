"""Tests for attachment metadata indexing (issue #73)."""

from __future__ import annotations

import unittest

from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.mapper import map_fixture_messages
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite


class AttachmentMetadataMapperTests(unittest.TestCase):
    def setUp(self):
        self.corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        self.result = map_fixture_messages(self.corpus.messages)

    def test_multi_attachment_record_captures_all_attachments(self):
        multi = next(r for r in self.result.records if r.fixture_id == "msg-007-multi-attach")
        self.assertEqual(multi.attachment_count, 3)
        self.assertEqual(len(multi.attachments), 3)

    def test_inline_image_attachment_flagged(self):
        multi = next(r for r in self.result.records if r.fixture_id == "msg-007-multi-attach")
        inline = next(a for a in multi.attachments if a.inline_flag)
        self.assertEqual(inline.filename, "chart.png")
        self.assertEqual(inline.content_type, "image/png")
        self.assertEqual(inline.content_id, "<chart-cid@example.test>")

    def test_non_inline_attachment_not_flagged(self):
        multi = next(r for r in self.result.records if r.fixture_id == "msg-007-multi-attach")
        pdf = next(a for a in multi.attachments if a.filename == "q1-report.pdf")
        self.assertFalse(pdf.inline_flag)
        self.assertIsNone(pdf.content_id)

    def test_missing_filename_is_empty_string(self):
        multi = next(r for r in self.result.records if r.fixture_id == "msg-007-multi-attach")
        no_name = next(a for a in multi.attachments if not a.filename)
        self.assertEqual(no_name.filename, "")
        self.assertEqual(no_name.content_type, "application/octet-stream")

    def test_pdf_attachment_without_content_id(self):
        legal = next(r for r in self.result.records if r.fixture_id == "msg-005-original")
        self.assertEqual(len(legal.attachments), 1)
        att = legal.attachments[0]
        self.assertEqual(att.filename, "intake.pdf")
        self.assertEqual(att.content_type, "application/pdf")
        self.assertIsNone(att.content_id)
        self.assertFalse(att.inline_flag)

    def test_empty_attachment_list_recorded(self):
        no_att = next(r for r in self.result.records if r.fixture_id == "msg-001")
        self.assertEqual(no_att.attachment_count, 0)
        self.assertEqual(len(no_att.attachments), 0)
        self.assertFalse(no_att.has_attachments)


class AttachmentMetadataSchemaTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_attachments_table_has_content_id_and_inline_flag(self):
        cols = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(attachments)").fetchall()
        }
        self.assertIn("content_id", cols)
        self.assertIn("inline_flag", cols)

    def test_attachment_content_type_index_exists(self):
        indexes = {
            row["name"]
            for row in self.conn.execute("PRAGMA index_list(attachments)").fetchall()
        }
        self.assertIn("idx_attachments_content_type", indexes)
        self.assertIn("idx_attachments_filename", indexes)

    def test_attachment_name_and_mime_filter_via_search(self):
        from mailplus_intelligence.index_writer import search_messages, write_index_records
        from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
        from mailplus_intelligence.mapper import map_fixture_messages

        corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
        records = map_fixture_messages(corpus.messages).records
        write_index_records(self.conn, records)

        pdf_results = search_messages(self.conn, attachment_mime_type="application/pdf")
        self.assertTrue(len(pdf_results) >= 1)

        name_results = search_messages(self.conn, attachment_name_contains="intake")
        self.assertTrue(len(name_results) >= 1)


if __name__ == "__main__":
    unittest.main()
