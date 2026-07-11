"""Selected-text cache store with class filter, TTL enforcement, and audit events."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .sqlite import enforce_owner_only_database_files

ALLOWED_CACHE_CLASSES = frozenset({
    "vip",
    "project",
    "admin",
    "financial",
    "travel",
    "legal",
})

DEFAULT_TTL_SECONDS = 7 * 24 * 3600
MAX_TTL_SECONDS = 30 * 24 * 3600
MAX_CACHE_TEXT_BYTES = 16 * 1024
ALLOWED_CACHE_PURPOSES = frozenset({"extraction", "review", "fixture-repro"})
ALLOWED_REDACTION_STATES = frozenset({"unreviewed", "redacted", "minimal", "synthetic"})
ALLOWED_PROVENANCE = frozenset({"operator-selected", "mailplus-fetch", "fixture"})
_AUDIT_LOCATOR = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_SECRET_SHAPED_LOCATOR = re.compile(
    r"(?i)(?:^|[-_.:/])(?:api[-_]?key|bearer|password|secret|token|sk-(?:live|test))(?:$|[-_.:/])"
)


class CachePolicyError(ValueError):
    """Raised when a selected-text cache request violates retention policy."""


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
    purpose: str = "extraction"
    redaction_state: str = "unreviewed"
    provenance: str = "operator-selected"
    review_required: bool = True
    disposed_at: str | None = None


def _record_event(
    connection: sqlite3.Connection,
    event_type: str,
    locator_export_id: str,
    message_class: str | None,
    detail_code: str | None = None,
) -> None:
    locator_ref = _audit_locator_ref(locator_export_id)
    connection.execute(
        """
        INSERT INTO text_cache_events (
          locator_ref, event_type, message_class, detail_code
        ) VALUES (?, ?, ?, ?)
        """,
        (locator_ref, event_type, message_class, detail_code),
    )


def _audit_locator_ref(locator_export_id: object) -> str:
    """Return a one-way audit reference without copying the source locator."""

    digest = hashlib.sha256(str(locator_export_id).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _require_clean_connection(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        raise CachePolicyError(
            "audited cache operations require a clean connection without an active transaction"
        )


@contextmanager
def _privacy_operation(connection: sqlite3.Connection):
    """Make a cache mutation and its audit event atomic without committing callers."""

    savepoint = "mpi_cache_privacy_operation"
    connection.execute(f"SAVEPOINT {savepoint}")
    try:
        yield
    except Exception:
        connection.execute(f"ROLLBACK TO {savepoint}")
        connection.execute(f"RELEASE {savepoint}")
        enforce_owner_only_database_files(connection)
        raise
    else:
        # Releasing the outermost savepoint commits. When a caller already owns
        # a transaction, this releases only our nested unit of work.
        connection.execute(f"RELEASE {savepoint}")
        enforce_owner_only_database_files(connection)


def _deny_policy(
    connection: sqlite3.Connection,
    locator_export_id: str,
    message_class: str | None,
    detail_code: str,
    message: str,
) -> None:
    with _privacy_operation(connection):
        _record_event(
            connection,
            "cache_policy_denied",
            locator_export_id,
            message_class,
            detail_code,
        )
    raise CachePolicyError(message)


def _validate_locator(
    connection: sqlite3.Connection,
    locator_export_id: object,
    message_class: str | None,
) -> None:
    if (
        not isinstance(locator_export_id, str)
        or not _AUDIT_LOCATOR.fullmatch(locator_export_id)
        or _SECRET_SHAPED_LOCATOR.search(locator_export_id)
    ):
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "locator-invalid",
            "locator must be a bounded privacy-safe identifier",
        )


def _validate_cache_request(
    connection: sqlite3.Connection,
    locator_export_id: str,
    message_class: str,
    text: str,
    ttl_seconds: int,
    purpose: str,
    redaction_state: str,
    provenance: str,
    review_required: bool,
) -> None:
    if not isinstance(text, str) or not text:
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "text-empty",
            "selected text must be a non-empty string",
        )
    if len(text.encode("utf-8")) > MAX_CACHE_TEXT_BYTES:
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "text-too-large",
            f"selected text must not exceed {MAX_CACHE_TEXT_BYTES} UTF-8 bytes",
        )
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "ttl-invalid-type",
            "ttl_seconds must be an integer",
        )
    if ttl_seconds < 0 or ttl_seconds > MAX_TTL_SECONDS:
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "ttl-out-of-range",
            f"ttl_seconds must be between 0 and {MAX_TTL_SECONDS}",
        )
    if purpose not in ALLOWED_CACHE_PURPOSES:
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "purpose-denied",
            "cache purpose is not permitted",
        )
    if redaction_state not in ALLOWED_REDACTION_STATES:
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "redaction-state-denied",
            "selected text must have an approved redaction state",
        )
    if provenance not in ALLOWED_PROVENANCE:
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "provenance-denied",
            "cache provenance is not permitted",
        )
    if not isinstance(review_required, bool):
        _deny_policy(
            connection,
            locator_export_id,
            message_class,
            "review-flag-invalid",
            "review_required must be a boolean",
        )


def cache_write(
    connection: sqlite3.Connection,
    locator_export_id: str,
    message_class: str,
    text: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    *,
    purpose: str = "extraction",
    redaction_state: str = "unreviewed",
    provenance: str = "operator-selected",
    review_required: bool = True,
) -> CacheEvent:
    """Write selected message text to cache if class is allowed."""

    _require_clean_connection(connection)
    _validate_locator(
        connection,
        locator_export_id,
        message_class if message_class in ALLOWED_CACHE_CLASSES else None,
    )
    if message_class not in ALLOWED_CACHE_CLASSES:
        with _privacy_operation(connection):
            _record_event(
                connection,
                "cache_class_denied",
                locator_export_id,
                None,
                "class-denied",
            )
        return CacheEvent(
            "cache_class_denied",
            locator_export_id,
            None,
            "class not in allowed set",
        )

    _validate_cache_request(
        connection,
        locator_export_id,
        message_class,
        text,
        ttl_seconds,
        purpose,
        redaction_state,
        provenance,
        review_required,
    )

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)

    with _privacy_operation(connection):
        connection.execute(
            """
            INSERT INTO text_cache (
              locator_export_id, message_class, cached_text, content_hash, cached_at,
              expires_at, purpose, redaction_state, provenance, review_required
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(locator_export_id) DO UPDATE SET
              message_class = excluded.message_class,
              cached_text = excluded.cached_text,
              content_hash = excluded.content_hash,
              cached_at = excluded.cached_at,
              expires_at = excluded.expires_at,
              evicted_at = NULL,
              purpose = excluded.purpose,
              redaction_state = excluded.redaction_state,
              provenance = excluded.provenance,
              review_required = excluded.review_required,
              disposed_at = NULL
            """,
            (
                locator_export_id,
                message_class,
                text,
                content_hash,
                now.isoformat(),
                expires_at.isoformat(),
                purpose,
                redaction_state,
                provenance,
                int(review_required),
            ),
        )
        _record_event(connection, "cache_write", locator_export_id, message_class)
        if ttl_seconds == 0:
            _dispose_entry(
                connection,
                locator_export_id,
                message_class,
                now.isoformat(),
                expired=True,
            )
    return CacheEvent("cache_write", locator_export_id, message_class, None)


def cache_read(
    connection: sqlite3.Connection,
    locator_export_id: str,
) -> tuple[str | None, CacheEvent]:
    """Read cached text for a locator. Returns (text, event) — text is None on miss/expiry."""

    _require_clean_connection(connection)
    _validate_locator(connection, locator_export_id, None)
    now = datetime.now(timezone.utc).isoformat()
    row = connection.execute(
        """
        SELECT cached_text, message_class, expires_at, evicted_at, disposed_at
        FROM text_cache WHERE locator_export_id = ?
        """,
        (locator_export_id,),
    ).fetchone()

    if row is None:
        with _privacy_operation(connection):
            _record_event(connection, "cache_miss", locator_export_id, None, "not-found")
        return None, CacheEvent("cache_miss", locator_export_id, None, "not found")

    if row["disposed_at"] is not None or row["evicted_at"] is not None:
        with _privacy_operation(connection):
            _record_event(
                connection,
                "cache_miss",
                locator_export_id,
                row["message_class"],
                "disposed",
            )
        return None, CacheEvent("cache_miss", locator_export_id, row["message_class"], "disposed")

    if row["expires_at"] <= now:
        with _privacy_operation(connection):
            _dispose_entry(connection, locator_export_id, row["message_class"], now, expired=True)
            _record_event(
                connection,
                "cache_miss",
                locator_export_id,
                row["message_class"],
                "expired",
            )
        return None, CacheEvent("cache_miss", locator_export_id, row["message_class"], "expired")

    with _privacy_operation(connection):
        _record_event(connection, "cache_read", locator_export_id, row["message_class"])
    return row["cached_text"], CacheEvent("cache_hit", locator_export_id, row["message_class"], None)


def _dispose_entry(
    connection: sqlite3.Connection,
    locator_export_id: str,
    message_class: str,
    disposed_at: str,
    *,
    expired: bool,
    expires_before: str | None = None,
) -> bool:
    cursor = connection.execute(
        """
        UPDATE text_cache
        SET cached_text = '', evicted_at = ?, disposed_at = ?
        WHERE locator_export_id = ?
          AND disposed_at IS NULL
          AND (? IS NULL OR expires_at <= ?)
        """,
        (
            disposed_at,
            disposed_at,
            locator_export_id,
            expires_before,
            expires_before,
        ),
    )
    if cursor.rowcount == 0:
        return False
    if expired:
        _record_event(connection, "cache_expiry", locator_export_id, message_class)
    _record_event(connection, "cache_disposal", locator_export_id, message_class, "text-overwritten")
    return True


def cache_evict_expired(connection: sqlite3.Connection) -> int:
    """Overwrite expired selected text and retain privacy-safe tombstones."""

    _require_clean_connection(connection)
    now = datetime.now(timezone.utc).isoformat()
    rows = connection.execute(
        """
        SELECT locator_export_id, message_class FROM text_cache
        WHERE expires_at <= ? AND disposed_at IS NULL
        """,
        (now,),
    ).fetchall()
    disposed_count = 0
    with _privacy_operation(connection):
        for row in rows:
            if _dispose_entry(
                connection,
                row["locator_export_id"],
                row["message_class"],
                now,
                expired=True,
                expires_before=now,
            ):
                disposed_count += 1
    return disposed_count


def cache_stats(connection: sqlite3.Connection) -> dict:
    """Return summary stats for the cache store."""

    now = datetime.now(timezone.utc).isoformat()
    total = connection.execute("SELECT COUNT(*) FROM text_cache").fetchone()[0]
    active = connection.execute(
        """
        SELECT COUNT(*) FROM text_cache
        WHERE expires_at > ? AND evicted_at IS NULL AND disposed_at IS NULL
        """,
        (now,),
    ).fetchone()[0]
    expired = total - active
    disposed = connection.execute(
        "SELECT COUNT(*) FROM text_cache WHERE disposed_at IS NOT NULL"
    ).fetchone()[0]
    return {
        "total": total,
        "active": active,
        "expired_or_evicted": expired,
        "disposed": disposed,
    }
