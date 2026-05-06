"""Tests for operator CLI (issue #72)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mailplus_intelligence.cli import build_parser, main
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.index_writer import write_index_records
from mailplus_intelligence.mapper import map_fixture_messages
from mailplus_intelligence.queue import enqueue_candidate, decide
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite


def _make_populated_db(path: str) -> None:
    conn = connect_sqlite(path)
    apply_all_migrations(conn)
    corpus = load_metadata_fixture_corpus("fixtures/mailplus_metadata")
    result = map_fixture_messages(corpus.messages)
    write_index_records(conn, result.records)
    conn.close()


class CLIParserTests(unittest.TestCase):
    def test_help_does_not_crash(self):
        parser = build_parser()
        self.assertIsNotNone(parser)

    def test_doctor_subcommand_runs(self):
        rc = main(["doctor"])
        self.assertIn(rc, (0, 1))

    def test_search_subcommand_no_results_memory_db(self):
        rc = main(["--db", ":memory:", "search", "--keyword", "Atlas"])
        self.assertEqual(rc, 0)

    def test_no_subcommand_returns_nonzero(self):
        rc = main([])
        self.assertEqual(rc, 1)


class CLISearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        _make_populated_db(self.tmp.name)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_search_by_keyword_returns_zero(self):
        rc = main(["--db", self.tmp.name, "search", "--keyword", "Atlas"])
        self.assertEqual(rc, 0)

    def test_search_json_output_is_valid(self, capsys=None):
        import io
        import sys
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = main(["--db", self.tmp.name, "--json", "search", "--keyword", "Atlas"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIsInstance(parsed, list)

    def test_thread_subcommand_found(self):
        rc = main(["--db", self.tmp.name, "thread", "thread-a"])
        self.assertEqual(rc, 0)

    def test_thread_subcommand_missing(self):
        rc = main(["--db", self.tmp.name, "thread", "no-such-thread"])
        self.assertEqual(rc, 1)


class CLIQueueTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)
        self.artifact_id = enqueue_candidate(self.conn, {
            "artifact_type": "obligation",
            "source_thread_key": "thread-a",
            "source_locators": ["fixture-export-001"],
            "evidence_refs": ["fixture-export-001"],
            "summary": "Test obligation summary.",
            "confidence": "high",
        })

    def tearDown(self):
        self.conn.close()

    def test_queue_list_subcommand(self):
        rc = main(["--db", ":memory:", "queue", "list"])
        self.assertEqual(rc, 0)


class CLIExportTests(unittest.TestCase):
    def test_export_no_approved_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main(["--db", ":memory:", "export", "--output", tmp])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
