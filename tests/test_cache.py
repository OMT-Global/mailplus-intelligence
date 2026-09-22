"""Tests for selected-text cache store (issue #69)."""

from __future__ import annotations

import sqlite3
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import mailplus_intelligence.cache as cache_module

from mailplus_intelligence.cache import (
    ALLOWED_CACHE_CLASSES,
    MAX_CACHE_TEXT_BYTES,
    MAX_TTL_SECONDS,
    CachePolicyError,
    _audit_locator_ref,
    cache_evict_expired,
    cache_read,
    cache_stats,
    cache_write,
)
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite


class TextCacheTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect_sqlite()
        apply_all_migrations(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_write_and_read_allowed_class(self):
        event = cache_write(self.conn, "exp-001", "vip", "Hello VIP text")
        self.assertEqual(event.event_type, "cache_write")

        text, read_event = cache_read(self.conn, "exp-001")
        self.assertEqual(text, "Hello VIP text")
        self.assertEqual(read_event.event_type, "cache_hit")

    def test_denied_class_not_written(self):
        event = cache_write(self.conn, "exp-noise", "ignore_noise", "Noise body")
        self.assertEqual(event.event_type, "cache_class_denied")

        text, read_event = cache_read(self.conn, "exp-noise")
        self.assertIsNone(text)
        self.assertEqual(read_event.event_type, "cache_miss")

    def test_all_allowed_classes_can_be_written(self):
        for cls in ALLOWED_CACHE_CLASSES:
            event = cache_write(self.conn, f"exp-{cls}", cls, f"text for {cls}")
            self.assertEqual(event.event_type, "cache_write", f"failed for class {cls}")

    def test_cache_miss_for_unknown_locator(self):
        text, event = cache_read(self.conn, "exp-does-not-exist")
        self.assertIsNone(text)
        self.assertEqual(event.event_type, "cache_miss")
        self.assertIn("not found", event.detail)

    def test_ttl_expiry_returns_miss(self):
        sentinel = "project-zero-ttl-sentinel"
        cache_write(self.conn, "exp-ttl", "project", sentinel, ttl_seconds=0)
        row = self.conn.execute(
            "SELECT cached_text, disposed_at FROM text_cache WHERE locator_export_id = 'exp-ttl'"
        ).fetchone()
        self.assertEqual(row["cached_text"], "")
        self.assertIsNotNone(row["disposed_at"])
        text, event = cache_read(self.conn, "exp-ttl")
        self.assertIsNone(text)
        self.assertIn("disposed", event.detail)

    def test_eviction_runs_and_marks_entries(self):
        sentinel = "legal-sentinel-text"
        cache_write(self.conn, "exp-evict-1", "legal", sentinel, ttl_seconds=3600)
        cache_write(self.conn, "exp-evict-2", "travel", "travel text", ttl_seconds=3600)
        self.conn.execute(
            "UPDATE text_cache SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE locator_export_id = 'exp-evict-1'"
        )
        self.conn.commit()
        count = cache_evict_expired(self.conn)
        self.assertGreaterEqual(count, 1)

        text, event = cache_read(self.conn, "exp-evict-1")
        self.assertIsNone(text)
        row = self.conn.execute(
            "SELECT cached_text, disposed_at FROM text_cache WHERE locator_export_id = ?",
            ("exp-evict-1",),
        ).fetchone()
        self.assertEqual(row["cached_text"], "")
        self.assertIsNotNone(row["disposed_at"])

        audit_rows = self.conn.execute(
            "SELECT event_type, detail_code FROM text_cache_events WHERE locator_ref = ?",
            (_audit_locator_ref("exp-evict-1"),),
        ).fetchall()
        self.assertTrue({"cache_expiry", "cache_disposal"}.issubset(
            {row["event_type"] for row in audit_rows}
        ))
        self.assertNotIn(sentinel, repr([tuple(row) for row in audit_rows]))

    def test_expiry_sweep_does_not_dispose_a_concurrently_refreshed_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "cache-race.db"
            sweep_connection = connect_sqlite(database)
            refresh_connection = connect_sqlite(database)
            try:
                apply_all_migrations(sweep_connection)
                cache_write(
                    sweep_connection,
                    "exp-race",
                    "vip",
                    "stale selected text",
                    ttl_seconds=3600,
                )
                sweep_connection.execute(
                    "UPDATE text_cache SET expires_at = ? WHERE locator_export_id = ?",
                    ("2000-01-01T00:00:00+00:00", "exp-race"),
                )
                sweep_connection.commit()

                original_privacy_operation = cache_module._privacy_operation
                refreshed = False

                @contextmanager
                def refresh_before_disposal(connection):
                    nonlocal refreshed
                    if not refreshed:
                        refreshed = True
                        cache_write(
                            refresh_connection,
                            "exp-race",
                            "vip",
                            "fresh selected text",
                            ttl_seconds=3600,
                        )
                    with original_privacy_operation(connection):
                        yield

                with patch.object(
                    cache_module,
                    "_privacy_operation",
                    refresh_before_disposal,
                ):
                    self.assertEqual(cache_evict_expired(sweep_connection), 0)

                row = sweep_connection.execute(
                    "SELECT cached_text, expires_at, disposed_at FROM text_cache "
                    "WHERE locator_export_id = ?",
                    ("exp-race",),
                ).fetchone()
                self.assertEqual(row["cached_text"], "fresh selected text")
                self.assertGreater(row["expires_at"], "2000-01-01T00:00:00+00:00")
                self.assertIsNone(row["disposed_at"])
            finally:
                refresh_connection.close()
                sweep_connection.close()

    def test_cache_stats_counts_active_and_expired(self):
        cache_write(self.conn, "exp-stat-1", "admin", "text", ttl_seconds=3600)
        cache_write(self.conn, "exp-stat-2", "financial", "text", ttl_seconds=0)
        stats = cache_stats(self.conn)
        self.assertGreaterEqual(stats["total"], 2)
        self.assertGreaterEqual(stats["active"], 1)

    def test_upsert_overwrites_existing_entry(self):
        cache_write(self.conn, "exp-upsert", "vip", "original", ttl_seconds=3600)
        cache_write(self.conn, "exp-upsert", "vip", "updated", ttl_seconds=3600)
        text, _ = cache_read(self.conn, "exp-upsert")
        self.assertEqual(text, "updated")

    def test_audit_event_carries_locator_and_class(self):
        event = cache_write(self.conn, "exp-audit", "legal", "some text")
        self.assertEqual(event.locator_export_id, "exp-audit")
        self.assertEqual(event.message_class, "legal")

    def test_invalid_ttls_fail_closed_and_are_audited(self):
        for locator, ttl in (("exp-negative", -1), ("exp-too-long", MAX_TTL_SECONDS + 1)):
            with self.assertRaises(CachePolicyError):
                cache_write(self.conn, locator, "project", "bounded text", ttl_seconds=ttl)
            self.assertIsNone(
                self.conn.execute(
                    "SELECT 1 FROM text_cache WHERE locator_export_id = ?", (locator,)
                ).fetchone()
            )
            event = self.conn.execute(
                "SELECT event_type, detail_code FROM text_cache_events WHERE locator_ref = ?",
                (_audit_locator_ref(locator),),
            ).fetchone()
            self.assertEqual(tuple(event), ("cache_policy_denied", "ttl-out-of-range"))

    def test_cache_rows_record_complete_lifecycle_metadata(self):
        cache_write(
            self.conn,
            "exp-lifecycle",
            "legal",
            "minimal selected text",
            purpose="review",
            redaction_state="minimal",
            provenance="mailplus-fetch",
            review_required=True,
        )
        row = self.conn.execute(
            """
            SELECT purpose, redaction_state, provenance, review_required,
                   cached_at, expires_at, disposed_at
            FROM text_cache WHERE locator_export_id = ?
            """,
            ("exp-lifecycle",),
        ).fetchone()
        self.assertEqual(row["purpose"], "review")
        self.assertEqual(row["redaction_state"], "minimal")
        self.assertEqual(row["provenance"], "mailplus-fetch")
        self.assertEqual(row["review_required"], 1)
        self.assertTrue(row["cached_at"])
        self.assertTrue(row["expires_at"])
        self.assertIsNone(row["disposed_at"])

    def test_durable_events_cover_write_read_miss_and_denial_without_text(self):
        sentinel = "never-persist-this-audit-sentinel"
        cache_write(self.conn, "exp-events", "vip", sentinel)
        cache_read(self.conn, "exp-events")
        cache_read(self.conn, "exp-missing")
        cache_write(self.conn, "exp-denied", "ignore_noise", sentinel)

        rows = self.conn.execute(
            "SELECT locator_ref, event_type, message_class, detail_code FROM text_cache_events"
        ).fetchall()
        event_types = {row["event_type"] for row in rows}
        self.assertTrue(
            {"cache_write", "cache_read", "cache_miss", "cache_class_denied"}.issubset(
                event_types
            )
        )
        self.assertNotIn(sentinel, repr([tuple(row) for row in rows]))

    def test_unsafe_locator_is_never_copied_into_audit_events(self):
        credential_sentinel = "sk-" + "live-secret-token"
        for sentinel in ("token=never-copy-this-secret", credential_sentinel):
            with self.assertRaises(CachePolicyError):
                cache_write(self.conn, sentinel, "vip", "selected text")
            self.assertIsNone(
                self.conn.execute(
                    "SELECT 1 FROM text_cache WHERE locator_export_id = ?",
                    (sentinel,),
                ).fetchone()
            )
        rows = self.conn.execute("SELECT locator_ref, detail_code FROM text_cache_events").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["locator_ref"].startswith("sha256:") for row in rows))
        self.assertTrue(all(row["detail_code"] == "locator-invalid" for row in rows))
        self.assertNotIn("never-copy-this-secret", repr([tuple(row) for row in rows]))

    def test_cache_read_rejects_an_active_caller_transaction(self):
        cache_write(self.conn, "exp-transaction", "vip", "selected text")
        self.conn.execute("CREATE TABLE caller_work (value TEXT NOT NULL)")
        self.conn.commit()
        self.conn.execute("INSERT INTO caller_work (value) VALUES ('pending')")

        with self.assertRaisesRegex(CachePolicyError, "clean connection"):
            cache_read(self.conn, "exp-transaction")
        self.conn.rollback()

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0], 0)

    def test_oversized_selected_text_is_rejected_before_persistence(self):
        sentinel = "x" * (MAX_CACHE_TEXT_BYTES + 1)
        with self.assertRaisesRegex(CachePolicyError, "must not exceed"):
            cache_write(self.conn, "exp-oversized", "legal", sentinel)
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM text_cache WHERE locator_export_id = 'exp-oversized'"
            ).fetchone()
        )
        audit = self.conn.execute(
            "SELECT detail_code FROM text_cache_events WHERE locator_ref = ?",
            (_audit_locator_ref("exp-oversized"),),
        ).fetchone()
        self.assertEqual(audit["detail_code"], "text-too-large")

    def test_cache_write_rolls_back_when_audit_insert_fails(self):
        self.conn.execute(
            """
            CREATE TRIGGER reject_cache_audit
            BEFORE INSERT ON text_cache_events
            BEGIN
              SELECT RAISE(ABORT, 'audit unavailable');
            END
            """
        )
        self.conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            cache_write(self.conn, "exp-atomic", "legal", "must-not-survive")
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM text_cache WHERE locator_export_id = 'exp-atomic'"
            ).fetchone()
        )

    def test_evicted_marker_cannot_retain_selected_text(self):
        cache_write(self.conn, "exp-evicted-guard", "legal", "recoverable-sentinel")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot retain"):
            self.conn.execute(
                "UPDATE text_cache SET evicted_at = CURRENT_TIMESTAMP "
                "WHERE locator_export_id = 'exp-evicted-guard'"
            )
        self.conn.rollback()
        row = self.conn.execute(
            "SELECT evicted_at, disposed_at FROM text_cache "
            "WHERE locator_export_id = 'exp-evicted-guard'"
        ).fetchone()
        self.assertIsNone(row["evicted_at"])
        self.assertIsNone(row["disposed_at"])

    def test_database_and_existing_wal_sidecars_are_owner_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "cache.db"
            connection = connect_sqlite(database)
            try:
                apply_all_migrations(connection)
                cache_write(connection, "exp-permissions", "admin", "selected text")
                candidates = [database, Path(f"{database}-wal"), Path(f"{database}-shm")]
                existing = [candidate for candidate in candidates if candidate.exists()]
                self.assertTrue(existing)
                for candidate in existing:
                    self.assertEqual(stat.S_IMODE(candidate.stat().st_mode), 0o600)
            finally:
                connection.close()

    def test_privacy_migration_disposes_legacy_evicted_text(self):
        connection = connect_sqlite()
        try:
            migrations = Path("src/mailplus_intelligence/migrations")
            for filename in (
                "001_metadata_schema_v0.sql",
                "002_attachment_metadata.sql",
                "003_cache_and_queue.sql",
            ):
                connection.executescript((migrations / filename).read_text(encoding="utf-8"))
            connection.execute(
                """
                INSERT INTO text_cache (
                  locator_export_id, message_class, cached_text, content_hash,
                  expires_at, evicted_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-evicted",
                    "legal",
                    "legacy-sensitive-text",
                    "hash-only",
                    "2099-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            connection.commit()

            apply_all_migrations(connection)
            row = connection.execute(
                """
                SELECT cached_text, disposed_at, purpose, redaction_state, provenance
                FROM text_cache WHERE locator_export_id = 'legacy-evicted'
                """
            ).fetchone()
            self.assertEqual(row["cached_text"], "")
            self.assertTrue(row["disposed_at"])
            self.assertEqual(row["purpose"], "legacy-migration")
            self.assertEqual(row["redaction_state"], "legacy-unknown")
            self.assertEqual(row["provenance"], "legacy")
            events = connection.execute(
                "SELECT locator_ref, event_type FROM text_cache_events"
            ).fetchall()
            self.assertIn("cache_disposal", {event["event_type"] for event in events})
            self.assertTrue(all(event["locator_ref"].startswith("legacy-row:") for event in events))
            self.assertNotIn("legacy-evicted", repr([tuple(event) for event in events]))
        finally:
            connection.close()

    def test_privacy_migration_rolls_back_all_schema_changes_on_failure(self):
        connection = connect_sqlite()
        try:
            migrations = Path("src/mailplus_intelligence/migrations")
            for filename in (
                "001_metadata_schema_v0.sql",
                "002_attachment_metadata.sql",
                "003_cache_and_queue.sql",
            ):
                connection.executescript((migrations / filename).read_text(encoding="utf-8"))
            script = (migrations / "005_cache_privacy.sql").read_text(encoding="utf-8")
            script = script.replace(
                "PRAGMA user_version = 5;",
                "SELECT missing_migration_function();",
            )
            with self.assertRaises(sqlite3.OperationalError):
                connection.executescript(script)
            connection.rollback()

            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(text_cache)")
            }
            self.assertNotIn("purpose", columns)
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                3,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
