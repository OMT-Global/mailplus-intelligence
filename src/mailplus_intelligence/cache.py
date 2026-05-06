"""Selected-text cache store with class filter, TTL enforcement, and audit events."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

ALLOWED_CACHE_CLASSES = frozenset({
    "vip",
    "project",
    "admin",
    "financial",
    "travel",
    "legal",
})

DEFAULT_TTL_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class CacheEvent:
    """Audit event emitted by cache operations."""

    event_type: str
    locator_export_id: str
    message_class: str | None
    detail: str | None


@dataclass(frozen=True)
class CacheEntry:
    """A text cache entry without the raw cached text."""

    locator_export_id: str
    message_class: str
    content_hash: str
    cached_at: str
    expires_at: str


def cache_write(
    connection: sqlite3.Connection,
    locator_export_id: str,
    message_class: str,
    text: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> CacheEvent:
    """Write selected message text to cache if class is allowed."""

    if message_class not in ALLOWED_CACHE_CLASSES:
        return CacheEvent("cache_class_denied", locator_export_id, message_class, f"class '{message_class}' not in allowed set")

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)

    connection.execute(
        """
        INSERT INTO text_cache (locator_export_id, message_class, cached_text, content_hash, cached_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(locator_export_id) DO UPDATE SET
          message_class = excluded.message_class,
          cached_text = excluded.cached_text,
          content_hash = excluded.content_hash,
          cached_at = excluded.cached_at,
          expires_at = excluded.expires_at,
          evicted_at = NULL
        """,
        (
            locator_export_id,
            message_class,
            text,
            content_hash,
            now.isoformat(),
            expires_at.isoformat(),
        ),
    )
    connection.commit()
    return CacheEvent("cache_write", locator_export_id, message_class, None)


def cache_read(
    connection: sqlite3.Connection,
    locator_export_id: str,
) -> tuple[str | None, CacheEvent]:
    """Read cached text for a locator. Returns (text, event) — text is None on miss/expiry."""

    now = datetime.now(timezone.utc).isoformat()
    row = connection.execute(
        "SELECT cached_text, message_class, expires_at, evicted_at FROM text_cache WHERE locator_export_id = ?",
        (locator_export_id,),
    ).fetchone()

    if row is None:
        return None, CacheEvent("cache_miss", locator_export_id, None, "not found")

    if row["evicted_at"] is not None:
        return None, CacheEvent("cache_miss", locator_export_id, row["message_class"], "evicted")

    if row["expires_at"] <= now:
        return None, CacheEvent("cache_miss", locator_export_id, row["message_class"], "expired")

    return row["cached_text"], CacheEvent("cache_hit", locator_export_id, row["message_class"], None)


def cache_evict_expired(connection: sqlite3.Connection) -> int:
    """Mark all expired entries as evicted. Returns count evicted."""

    now = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        "UPDATE text_cache SET evicted_at = ? WHERE expires_at <= ? AND evicted_at IS NULL",
        (now, now),
    )
    connection.commit()
    return cursor.rowcount


def cache_stats(connection: sqlite3.Connection) -> dict:
    """Return summary stats for the cache store."""

    now = datetime.now(timezone.utc).isoformat()
    total = connection.execute("SELECT COUNT(*) FROM text_cache").fetchone()[0]
    active = connection.execute(
        "SELECT COUNT(*) FROM text_cache WHERE expires_at > ? AND evicted_at IS NULL", (now,)
    ).fetchone()[0]
    expired = total - active
    return {"total": total, "active": active, "expired_or_evicted": expired}
