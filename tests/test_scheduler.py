"""Tests for scheduler.py job locking and lifecycle events."""

from __future__ import annotations

import time
import unittest

from mailplus_intelligence.scheduler import (
    CACHE_DISPOSAL_JOB,
    LOCK_STALE_SECONDS,
    JobEvent,
    acquire_lock,
    get_job_status,
    list_jobs,
    release_lock,
    run_cache_disposal_job,
    run_job,
)
from mailplus_intelligence.cache import cache_write
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite


class SchedulerLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect_sqlite(":memory:")

    def tearDown(self) -> None:
        self.conn.close()

    def test_acquire_and_release(self) -> None:
        acquired, events = acquire_lock(self.conn, "test-job")
        self.assertTrue(acquired)
        self.assertTrue(any(e.event == "acquired" for e in events))

        status = get_job_status(self.conn, "test-job")
        self.assertIsNotNone(status)
        self.assertTrue(status.locked)

        release_events = release_lock(self.conn, "test-job", success=True)
        self.assertTrue(any(e.event == "released" for e in release_events))

        status = get_job_status(self.conn, "test-job")
        self.assertFalse(status.locked)
        self.assertIsNotNone(status.last_success_at)

    def test_second_acquire_skipped_while_locked(self) -> None:
        acquire_lock(self.conn, "test-job")
        acquired2, events2 = acquire_lock(self.conn, "test-job")
        self.assertFalse(acquired2)
        self.assertTrue(any(e.event == "skipped" for e in events2))

    def test_stale_lock_cleared_on_acquire(self) -> None:
        from datetime import datetime, timedelta, timezone

        # Manually insert a stale lock.
        from mailplus_intelligence.scheduler import _ensure_scheduler_table
        _ensure_scheduler_table(self.conn)
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=LOCK_STALE_SECONDS + 10)).isoformat()
        self.conn.execute(
            "INSERT INTO scheduler_locks (job_name, locked, locked_at, lock_holder) VALUES (?, 1, ?, ?)",
            ("stale-job", stale_time, "old-holder"),
        )
        self.conn.commit()

        acquired, events = acquire_lock(self.conn, "stale-job")
        self.assertTrue(acquired)
        self.assertTrue(any(e.event == "stale_cleared" for e in events))

    def test_run_job_executes_fn(self) -> None:
        results = []
        ran, result = run_job(self.conn, "fn-job", lambda: results.append(1) or "done")
        self.assertTrue(ran)
        self.assertEqual(result, "done")
        self.assertEqual(results, [1])
        status = get_job_status(self.conn, "fn-job")
        self.assertFalse(status.locked)
        self.assertIsNotNone(status.last_success_at)

    def test_run_job_skips_when_locked(self) -> None:
        acquire_lock(self.conn, "fn-job")
        ran, result = run_job(self.conn, "fn-job", lambda: 99)
        self.assertFalse(ran)
        self.assertIsNone(result)

    def test_run_job_releases_on_exception(self) -> None:
        def boom():
            raise ValueError("oops")

        with self.assertRaises(ValueError):
            run_job(self.conn, "boom-job", boom)
        status = get_job_status(self.conn, "boom-job")
        self.assertFalse(status.locked)

    def test_list_jobs(self) -> None:
        acquire_lock(self.conn, "job-a")
        acquire_lock(self.conn, "job-b")
        jobs = list_jobs(self.conn)
        names = {j.job_name for j in jobs}
        self.assertIn("job-a", names)
        self.assertIn("job-b", names)

    def test_get_job_status_none_for_unknown(self) -> None:
        from mailplus_intelligence.scheduler import _ensure_scheduler_table
        _ensure_scheduler_table(self.conn)
        self.assertIsNone(get_job_status(self.conn, "unknown-job"))

    def test_event_sink_collects_events(self) -> None:
        sink: list[JobEvent] = []
        run_job(self.conn, "sink-job", lambda: None, event_sink=sink)
        event_types = {e.event for e in sink}
        self.assertIn("acquired", event_types)
        self.assertIn("released", event_types)

    def test_cache_disposal_job_overwrites_expired_selected_text(self) -> None:
        apply_all_migrations(self.conn)
        cache_write(self.conn, "scheduled-expiry", "legal", "selected sentinel")
        self.conn.execute(
            "UPDATE text_cache SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE locator_export_id = 'scheduled-expiry'"
        )
        self.conn.commit()

        ran, disposed = run_cache_disposal_job(self.conn)

        self.assertTrue(ran)
        self.assertEqual(disposed, 1)
        row = self.conn.execute(
            "SELECT cached_text, disposed_at FROM text_cache "
            "WHERE locator_export_id = 'scheduled-expiry'"
        ).fetchone()
        self.assertEqual(row["cached_text"], "")
        self.assertTrue(row["disposed_at"])
        status = get_job_status(self.conn, CACHE_DISPOSAL_JOB)
        self.assertFalse(status.locked)
        self.assertTrue(status.last_success_at)


if __name__ == "__main__":
    unittest.main()
