"""Recurring sync scheduler with job locking and stale detection (#74).

Provides a lightweight in-process scheduler backed by the SQLite index.
Prevents overlapping runs, detects stale locks, and emits lifecycle events.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


@dataclass(frozen=True)
class SyncLease:
    """An ownership token for a bounded scheduler lease.

    Callers must present this token to renew or release the lease.  A holder
    name is useful for diagnostics, but is never treated as authorization.
    """

    job_name: str
    holder: str
    token: str
    expires_at: str


def _ensure_scheduler_table(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduler_locks (
            job_name       TEXT PRIMARY KEY,
            locked         INTEGER NOT NULL DEFAULT 0,
            locked_at      TEXT,
            lock_holder    TEXT,
            lease_token    TEXT,
            lease_expires_at TEXT,
            heartbeat_at   TEXT,
            last_run_at    TEXT,
            last_success_at TEXT
        );
        """
    )
    # Existing local indexes predate leases.  SQLite's CREATE TABLE IF NOT
    # EXISTS cannot add the columns, so migrate the small runtime table in
    # place without requiring a separate application-schema migration.
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(scheduler_locks)")}
    for column, definition in (
        ("lease_token", "TEXT"),
        ("lease_expires_at", "TEXT"),
        ("heartbeat_at", "TEXT"),
    ):
        if column not in columns:
            connection.execute(f"ALTER TABLE scheduler_locks ADD COLUMN {column} {definition}")
    connection.commit()


def _lease_timestamps(ttl_seconds: int) -> tuple[str, str]:
    if ttl_seconds <= 0:
        raise ValueError("lease ttl_seconds must be positive")
    now = datetime.now(timezone.utc)
    return now.isoformat(), (now + timedelta(seconds=ttl_seconds)).isoformat()


def acquire_lease(
    connection: sqlite3.Connection,
    job_name: str,
    *,
    holder: str = "local",
    ttl_seconds: int = LOCK_STALE_SECONDS,
) -> tuple[SyncLease | None, list[JobEvent]]:
    """Atomically acquire a renewable job lease, or return ``None`` if held.

    Expired leases may be replaced.  The generated token is required for all
    subsequent ownership-sensitive operations.
    """

    _ensure_scheduler_table(connection)
    now, expires_at = _lease_timestamps(ttl_seconds)
    token = uuid.uuid4().hex
    previous = connection.execute(
        "SELECT locked, lease_expires_at FROM scheduler_locks WHERE job_name = ?", (job_name,)
    ).fetchone()
    cursor = connection.execute(
        """
        INSERT INTO scheduler_locks
          (job_name, locked, locked_at, lock_holder, lease_token, lease_expires_at, heartbeat_at, last_run_at)
        VALUES (?, 1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_name) DO UPDATE SET
          locked = 1, locked_at = excluded.locked_at, lock_holder = excluded.lock_holder,
          lease_token = excluded.lease_token, lease_expires_at = excluded.lease_expires_at,
          heartbeat_at = excluded.heartbeat_at, last_run_at = excluded.last_run_at
        WHERE scheduler_locks.locked = 0
           OR scheduler_locks.lease_expires_at IS NULL
           OR scheduler_locks.lease_expires_at <= excluded.locked_at
        """,
        (job_name, now, holder, token, expires_at, now, now),
    )
    connection.commit()
    if cursor.rowcount != 1:
        return None, [JobEvent(job_name, "skipped", "active lease held by another run")]
    events = [JobEvent(job_name, "acquired")]
    if previous and previous["locked"]:
        events.insert(0, JobEvent(job_name, "stale_cleared", "expired lease replaced"))
    return SyncLease(job_name, holder, token, expires_at), events


def renew_lease(
    connection: sqlite3.Connection,
    lease: SyncLease,
    *,
    ttl_seconds: int = LOCK_STALE_SECONDS,
) -> SyncLease | None:
    """Heartbeat an owned lease; return a refreshed lease or ``None`` on loss."""

    _ensure_scheduler_table(connection)
    now, expires_at = _lease_timestamps(ttl_seconds)
    cursor = connection.execute(
        """
        UPDATE scheduler_locks
        SET lease_expires_at = ?, heartbeat_at = ?
        WHERE job_name = ? AND locked = 1 AND lease_token = ? AND lease_expires_at > ?
        """,
        (expires_at, now, lease.job_name, lease.token, now),
    )
    connection.commit()
    if cursor.rowcount != 1:
        return None
    return SyncLease(lease.job_name, lease.holder, lease.token, expires_at)


def release_lease(
    connection: sqlite3.Connection,
    lease: SyncLease,
    *,
    success: bool = True,
) -> bool:
    """Release only the exact lease owner; stale owners cannot unlock a job."""

    _ensure_scheduler_table(connection)
    now = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        UPDATE scheduler_locks
        SET locked = 0, locked_at = NULL, lock_holder = NULL, lease_token = NULL,
            lease_expires_at = NULL, heartbeat_at = NULL,
            last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END
        WHERE job_name = ? AND locked = 1 AND lease_token = ?
        """,
        (1 if success else 0, now, lease.job_name, lease.token),
    )
    connection.commit()
    return cursor.rowcount == 1


def acquire_lock(
    connection: sqlite3.Connection,
    job_name: str,
    holder: str = "local",
) -> tuple[bool, list[JobEvent]]:
    """Try to acquire a named job lock.

    Clears stale locks automatically.  Returns (acquired, events).
    """
    lease, events = acquire_lease(connection, job_name, holder=holder)
    return lease is not None, events


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
    lease, events = acquire_lease(connection, job_name, holder=holder)
    if event_sink is not None:
        event_sink.extend(events)
    if lease is None:
        return False, None

    try:
        result = fn()
        released = release_lease(connection, lease, success=True)
    except Exception as exc:
        released = release_lease(connection, lease, success=False)
        release_events = [JobEvent(job_name, "released" if released else "error", "failure")]
        if event_sink is not None:
            event_sink.extend(release_events)
            event_sink.append(JobEvent(job_name, "error", str(exc)))
        raise

    release_events = [JobEvent(job_name, "released" if released else "error", "success")]
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
