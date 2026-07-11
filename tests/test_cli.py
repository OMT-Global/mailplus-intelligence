"""Tests for operator CLI (issue #72)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from mailplus_intelligence.cli import build_parser, main
from mailplus_intelligence.fixtures import load_metadata_fixture_corpus
from mailplus_intelligence.index_writer import write_index_records
from mailplus_intelligence.mapper import map_fixture_messages
from mailplus_intelligence.queue import enqueue_candidate, get_item, get_review_history
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

    def test_json_common_option_works_after_doctor(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main(["doctor", "--json"])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_search_subcommand_no_results_memory_db(self):
        rc = main(["--db", ":memory:", "search", "--keyword", "Atlas"])
        self.assertEqual(rc, 0)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_live_sync_requires_explicit_configuration_without_network_access(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main(["--json", "sync", "run", "--dry-run"])
        self.assertEqual(rc, 2)
        payload = json.loads(err.getvalue())
        self.assertIn("MAILPLUS_HOST", payload["error"])
        self.assertNotIn("synthetic-secret", payload["error"])

    def test_no_subcommand_returns_nonzero(self):
        rc = main([])
        self.assertEqual(rc, 1)

    def test_no_subcommand_json_error_is_machine_readable(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main(["--json"])
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(err.getvalue())["ok"])

    def test_version_option_prints_package_version(self):
        parser = build_parser()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("mpi ", buf.getvalue())

    def test_version_common_option_works_after_subcommand(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as raised:
            main(["doctor", "--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("mpi ", buf.getvalue())

    def test_memory_db_warning_is_actionable(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main(["search", "--keyword", "Atlas"])
        self.assertEqual(rc, 0)
        self.assertIn("--db :memory: does not persist", err.getvalue())

    def test_json_parse_errors_are_machine_readable_for_any_option_position(self):
        invalid_commands = (
            ["search", "--limit", "not-an-integer", "--json"],
            ["queue", "correct", "artifact-1", "--json"],
            ["--json", "search", "--unknown-option"],
            ["queue", "list", "--db", "--json"],
        )
        for command in invalid_commands:
            with self.subTest(command=command):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(command)
                self.assertEqual(rc, 2)
                payload = json.loads(err.getvalue())
                self.assertFalse(payload["ok"])
                self.assertTrue(payload["error"])

    def test_parse_errors_redact_secret_shaped_unknown_arguments(self):
        commands = (
            ["doctor", "--json", "--MAILPLUS_TOKEN=synthetic-token"],
            ["doctor", "--MAILPLUS_PASSWORD", "synthetic-password", "--json"],
            ["doctor", "--json", "https://synthetic-user:synthetic-pass@example.test/mail"],
        )
        for command in commands:
            with self.subTest(command=command):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(command)
                self.assertEqual(rc, 2)
                diagnostic = err.getvalue()
                payload = json.loads(diagnostic)
                self.assertFalse(payload["ok"])
                self.assertIn("<redacted", payload["error"])
                for secret in (
                    "synthetic-token",
                    "synthetic-password",
                    "synthetic-user",
                    "synthetic-pass",
                ):
                    self.assertNotIn(secret, diagnostic)

    def test_plain_parse_errors_redact_secret_shaped_unknown_arguments(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
            main(["doctor", "--MAILPLUS_TOKEN=synthetic-token"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--MAILPLUS_TOKEN=<redacted>", err.getvalue())
        self.assertNotIn("synthetic-token", err.getvalue())

    def test_parse_errors_redact_entire_multiword_secret_arguments(self):
        for json_mode in (False, True):
            secret = "entire secret value has multiple words"
            command = ["doctor", "--MAILPLUS_PASSWORD", secret]
            if json_mode:
                command.append("--json")
            err = io.StringIO()
            with self.subTest(json_mode=json_mode), contextlib.redirect_stderr(err):
                if json_mode:
                    rc = main(command)
                else:
                    with self.assertRaises(SystemExit) as raised:
                        main(command)
                    rc = raised.exception.code

            self.assertEqual(rc, 2)
            diagnostic = err.getvalue()
            self.assertIn("--MAILPLUS_PASSWORD <redacted>", diagnostic)
            self.assertNotIn(secret, diagnostic)
            for word in secret.split():
                self.assertNotIn(word, diagnostic)


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

    def test_common_options_work_after_search_arguments(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main([
                "search",
                "--keyword",
                "Atlas",
                "--db",
                self.tmp.name,
                "--json",
            ])
        self.assertEqual(rc, 0)
        self.assertGreater(len(json.loads(out.getvalue())), 0)

    def test_thread_subcommand_found(self):
        rc = main(["--db", self.tmp.name, "thread", "thread-a"])
        self.assertEqual(rc, 0)

    def test_thread_subcommand_missing(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = main(["--db", self.tmp.name, "thread", "no-such-thread", "--json"])
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(err.getvalue())["ok"])

    def test_history_subcommand_returns_metadata_only_timeline(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main(["--db", self.tmp.name, "history", "alice@example.test"])
        self.assertEqual(rc, 0)
        self.assertIn("locator:", out.getvalue())


class CLIQueueTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)
        self.artifact_id = enqueue_candidate(self.conn, {
            "artifact_type": "obligation",
            "source_thread_key": "thread-a",
            "source_message_ids": ["<fixture-message-001@example.test>"],
            "source_locators": ["fixture-export-001"],
            "evidence_refs": ["subject"],
            "summary": "Test obligation summary.",
            "confidence": "high",
            "review_status": "candidate",
            "provenance": "deterministic",
            "extractor_version": "metadata-extractor-v1",
            "model_version": None,
            "rule_version": "metadata-rules-v1",
            "created_at": "2026-01-10T10:00:00Z",
        })

    def tearDown(self):
        self.conn.close()

    def test_queue_list_subcommand(self):
        rc = main(["--db", ":memory:", "queue", "list"])
        self.assertEqual(rc, 0)

    def test_common_options_work_after_nested_queue_subcommand(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = main(["queue", "list", "--db", ":memory:", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), [])

    def test_queue_decision_failures_are_machine_readable(self):
        commands = (
            ["approve", "missing-artifact", "--reviewer", "operator@example.test", "--expected-revision", "0"],
            ["reject", "missing-artifact", "--reviewer", "operator@example.test", "--expected-revision", "0"],
            ["defer", "missing-artifact", "--reviewer", "operator@example.test", "--expected-revision", "0"],
            [
                "correct",
                "missing-artifact",
                "--corrected-summary",
                "corrected",
                "--reviewer",
                "operator@example.test",
                "--expected-revision",
                "0",
            ],
        )
        for decision in commands:
            with self.subTest(decision=decision):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = main(["queue", *decision, "--db", ":memory:", "--json"])
                self.assertEqual(rc, 2)
                payload = json.loads(err.getvalue())
                self.assertFalse(payload["ok"])
                self.assertIn("queue decision failed", payload["error"])

    def test_queue_decision_records_reviewer_and_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "review.db")
            connection = connect_sqlite(database)
            apply_all_migrations(connection)
            artifact_id = enqueue_candidate(connection, {
                "artifact_type": "obligation",
                "source_thread_key": "thread-cli",
                "source_message_ids": ["<cli@example.test>"],
                "source_locators": ["fixture-export-cli"],
                "evidence_refs": ["subject"],
                "summary": "CLI review candidate.",
                "confidence": "high",
                "review_status": "candidate",
                "provenance": "deterministic",
                "extractor_version": "metadata-extractor-v1",
                "model_version": None,
                "rule_version": "metadata-rules-v1",
                "created_at": "2026-01-10T10:00:00Z",
            })
            connection.close()

            rc = main([
                "--db", database, "queue", "approve", artifact_id,
                "--reviewer", "operator@example.test",
                "--expected-revision", "0",
            ])
            self.assertEqual(rc, 0)

            connection = connect_sqlite(database)
            item = get_item(connection, artifact_id)
            history = get_review_history(connection, artifact_id)
            connection.close()
            self.assertEqual(item.revision, 1)
            self.assertEqual(history[0].reviewer_identity, "operator@example.test")

            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                rc = main([
                    "--db", database, "queue", "reject", artifact_id,
                    "--reviewer", "second@example.test",
                    "--expected-revision", "0",
                ])
            self.assertEqual(rc, 2)
            self.assertIn("stale review", error.getvalue())



class CLIExportTests(unittest.TestCase):
    def test_export_no_approved_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main(["--db", ":memory:", "export", "--output", tmp])
            self.assertEqual(rc, 0)

    def test_export_json_is_machine_readable_when_queue_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main(["export", "--output", tmp, "--db", ":memory:", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue())["artifact_count"], 0)


class CLISeedTests(unittest.TestCase):
    def test_seed_populates_search_and_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "mpi.db")
            rc = main(["--db", db_path, "seed", "--from-fixtures", "fixtures/mailplus_metadata"])
            self.assertEqual(rc, 0)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                search_rc = main(["--db", db_path, "--json", "search", "--keyword", "Atlas"])
            self.assertEqual(search_rc, 0)
            self.assertGreater(len(json.loads(out.getvalue())), 0)

            queue_out = io.StringIO()
            with contextlib.redirect_stdout(queue_out):
                queue_rc = main(["--db", db_path, "queue", "list"])
            self.assertEqual(queue_rc, 0)
            self.assertIn("[candidate]", queue_out.getvalue())

    def test_seed_json_summary_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "mpi.db")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = main([
                    "seed",
                    "--from-fixtures",
                    "fixtures/mailplus_metadata",
                    "--db",
                    db_path,
                    "--json",
                ])
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["inserted"], 8)

    def test_seed_missing_fixture_path_prints_friendly_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "mpi.db")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main(["--db", db_path, "seed", "--from-fixtures", "missing-fixtures"])
            self.assertEqual(rc, 2)
            self.assertIn("file not found", err.getvalue())

    def test_seed_json_error_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main([
                    "seed",
                    "--from-fixtures",
                    "missing-fixtures",
                    "--db",
                    str(Path(tmp) / "mpi.db"),
                    "--json",
                ])
        self.assertEqual(rc, 2)
        self.assertFalse(json.loads(err.getvalue())["ok"])

    def test_missing_database_parent_prints_friendly_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "missing-parent" / "mpi.db")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main(["--db", db_path, "search", "--keyword", "Atlas"])
            self.assertEqual(rc, 2)
            self.assertIn("database parent directory", err.getvalue())


if __name__ == "__main__":
    unittest.main()
