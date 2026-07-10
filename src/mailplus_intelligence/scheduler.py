"""Recurring sync scheduler with job locking and stale detection (#74).

Provides a lightweight in-process scheduler backed by the SQLite index.
Prevents overlapping runs, detects stale locks, and emits lifecycle events.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


# Job lock TTL: a lock older than this is considered stale.
LOCK_STALE_SECONDS = 300
CACHE_DISPOSAL_JOB = "selected-text-cache-disposal"


@dataclass(frozen=True)
class JobEvent:
    job_name: str
    event: str          # acquired | released | skipped | stale_cleared | error
    detail: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(
                self, "timestamp", datetime.now(timezone.utc).isoformat()
            )


@dataclass
class JobStatus:
    job_name: str
    locked: bool
    locked_at: str | None
    last_run_at: str | None
    last_success_at: str | None
    lock_holder: str | None


def _ensure_scheduler_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduler_locks (
            job_name       TEXT PRIMARY KEY,
            locked         INTEGER NOT NULL DEFAULT 0,
            locked_at      TEXT,
            lock_holder    TEXT,
            last_run_at    TEXT,
            last_success_at TEXT
        );
        """
    )
    connection.commit()


def acquire_lock(
    connection: sqlite3.Connection,
    job_name: str,
    holder: str = "local",
) -> tuple[bool, list[JobEvent]]:
    """Try to acquire a named job lock.

    Clears stale locks automatically.  Returns (acquired, events).
    """
    _ensure_scheduler_table(connection)
    events: list[JobEvent] = []
    now = datetime.now(timezone.utc).isoformat()

    row = connection.execute(
        "SELECT locked, locked_at FROM scheduler_locks WHERE job_name = ?",
        (job_name,),
    ).fetchone()

    if row and row["locked"]:
        locked_at_str = row["locked_at"]
        if locked_at_str:
            try:
                locked_at = datetime.fromisoformat(locked_at_str)
                age = (datetime.now(timezone.utc) - locked_at).total_seconds()
                if age > LOCK_STALE_SECONDS:
                    connection.execute(
                        "UPDATE scheduler_locks SET locked = 0, locked_at = NULL, lock_holder = NULL "
                        "WHERE job_name = ?",
                        (job_name,),
                    )
                    connection.commit()
                    events.append(JobEvent(job_name, "stale_cleared", f"lock age {age:.0f}s"))
                else:
                    events.append(JobEvent(job_name, "skipped", "already locked"))
                    return False, events
            except ValueError:
                pass

    connection.execute(
        """
        INSERT INTO scheduler_locks (job_name, locked, locked_at, lock_holder, last_run_at)
        VALUES (?, 1, ?, ?, ?)
        ON CONFLICT(job_name) DO UPDATE SET
            locked = 1, locked_at = excluded.locked_at,
            lock_holder = excluded.lock_holder,
            last_run_at = excluded.last_run_at
        """,
        (job_name, now, holder, now),
    )
    connection.commit()
    events.append(JobEvent(job_name, "acquired"))
    return True, events


def release_lock(
    connection: sqlite3.Connection,
    job_name: str,
    *,
    success: bool = True,
) -> list[JobEvent]:
    """Release a previously acquired job lock."""
    _ensure_scheduler_table(connection)
    now = datetime.now(timezone.utc).isoformat()
    update = (
        "UPDATE scheduler_locks SET locked = 0, locked_at = NULL, lock_holder = NULL, "
        "last_success_at = ? WHERE job_name = ?"
        if success
        else "UPDATE scheduler_locks SET locked = 0, locked_at = NULL, lock_holder = NULL "
        "WHERE job_name = ?"
    )
    params = (now, job_name) if success else (job_name,)
    connection.execute(update, params)
    connection.commit()
    return [JobEvent(job_name, "released", "success" if success else "failure")]


def get_job_status(connection: sqlite3.Connection, job_name: str) -> JobStatus | None:
    """Return current status of a named job, or None if never registered."""
    _ensure_scheduler_table(connection)
    row = connection.execute(
        "SELECT * FROM scheduler_locks WHERE job_name = ?", (job_name,)
    ).fetchone()
    if not row:
        return None
    return JobStatus(
        job_name=row["job_name"],
        locked=bool(row["locked"]),
        locked_at=row["locked_at"],
        last_run_at=row["last_run_at"],
        last_success_at=row["last_success_at"],
        lock_holder=row["lock_holder"],
    )


def list_jobs(connection: sqlite3.Connection) -> list[JobStatus]:
    """Return status for all known jobs."""
    _ensure_scheduler_table(connection)
    rows = connection.execute("SELECT * FROM scheduler_locks ORDER BY job_name").fetchall()
    return [
        JobStatus(
            job_name=row["job_name"],
            locked=bool(row["locked"]),
            locked_at=row["locked_at"],
            last_run_at=row["last_run_at"],
            last_success_at=row["last_success_at"],
            lock_holder=row["lock_holder"],
        )
        for row in rows
    ]


def run_job(
    connection: sqlite3.Connection,
    job_name: str,
    fn: Callable[[], Any],
    *,
    holder: str = "local",
    event_sink: list[JobEvent] | None = None,
) -> tuple[bool, Any]:
    """Acquire lock, run fn(), release lock.  Returns (ran, result).

    Skips execution if lock cannot be acquired.
    """
    acquired, events = acquire_lock(connection, job_name, holder=holder)
    if event_sink is not None:
        event_sink.extend(events)
    if not acquired:
        return False, None

    try:
        result = fn()
        release_events = release_lock(connection, job_name, success=True)
    except Exception as exc:
        release_events = release_lock(connection, job_name, success=False)
        if event_sink is not None:
            event_sink.extend(release_events)
            event_sink.append(JobEvent(job_name, "error", str(exc)))
        raise

    if event_sink is not None:
        event_sink.extend(release_events)
    return True, result


def run_cache_disposal_job(
    connection: sqlite3.Connection,
    *,
    holder: str = "local",
    event_sink: list[JobEvent] | None = None,
) -> tuple[bool, int | None]:
    """Run the selected-text expiry/disposal sweep under the scheduler lock."""

    from .cache import cache_evict_expired

    ran, result = run_job(
        connection,
        CACHE_DISPOSAL_JOB,
        lambda: cache_evict_expired(connection),
        holder=holder,
        event_sink=event_sink,
    )
    return ran, result
