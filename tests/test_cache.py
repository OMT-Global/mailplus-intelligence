"""Tests for selected-text cache store (issue #69)."""

from __future__ import annotations

import time
import unittest

from mailplus_intelligence.cache import (
    ALLOWED_CACHE_CLASSES,
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
        cache_write(self.conn, "exp-ttl", "project", "project text", ttl_seconds=0)
        text, event = cache_read(self.conn, "exp-ttl")
        self.assertIsNone(text)
        self.assertIn("expired", event.detail)

    def test_eviction_runs_and_marks_entries(self):
        cache_write(self.conn, "exp-evict-1", "legal", "legal text", ttl_seconds=0)
        cache_write(self.conn, "exp-evict-2", "travel", "travel text", ttl_seconds=3600)
        count = cache_evict_expired(self.conn)
        self.assertGreaterEqual(count, 1)

        text, event = cache_read(self.conn, "exp-evict-1")
        self.assertIsNone(text)

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


if __name__ == "__main__":
    unittest.main()
