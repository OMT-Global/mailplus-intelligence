"""Write normalized IndexRecords into the SQLite metadata store."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .mapper import IndexRecord


@dataclass(frozen=True)
class WriteResult:
    """Summary of a batch index write."""

    inserted: int
    skipped: int
    errors: tuple[str, ...]


def write_index_records(
    connection: sqlite3.Connection,
    records: tuple["IndexRecord", ...],
) -> WriteResult:
    """Upsert IndexRecords into the SQLite metadata store.

    Skips records whose locator_export_id already exists (idempotent).
    """
    inserted = 0
    skipped = 0
    errors: list[str] = []

    for record in records:
        try:
            _upsert_record(connection, record)
            inserted += 1
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint" in str(exc):
                skipped += 1
            else:
                errors.append(f"{record.fixture_id}: {exc}")
        except Exception as exc:
            errors.append(f"{record.fixture_id}: {exc}")

    connection.commit()
    return WriteResult(inserted=inserted, skipped=skipped, errors=tuple(errors))


def _upsert_record(connection: sqlite3.Connection, record: "IndexRecord") -> None:
    mailbox_id = _ensure_mailbox(connection, record)
    thread_id = _ensure_thread(connection, record)
    message_id = _insert_message(connection, record, mailbox_id, thread_id)
    _insert_participants(connection, record, message_id)
    _insert_labels(connection, record, message_id)
    _insert_flags(connection, record, message_id)
    _insert_relationships(connection, record, message_id)
    _insert_attachments(connection, record, message_id)


def _ensure_mailbox(connection: sqlite3.Connection, record: "IndexRecord") -> int:
    connection.execute(
        """
        INSERT OR IGNORE INTO mailboxes (account, mailbox, folder_path)
        VALUES (?, ?, ?)
        """,
        (record.locator_account, record.locator_mailbox, record.folder_path),
    )
    row = connection.execute(
        "SELECT id FROM mailboxes WHERE account = ? AND mailbox = ? AND folder_path = ?",
        (record.locator_account, record.locator_mailbox, record.folder_path),
    ).fetchone()
    return int(row["id"])


def _ensure_thread(connection: sqlite3.Connection, record: "IndexRecord") -> int:
    connection.execute(
        """
        INSERT OR IGNORE INTO threads (thread_key, subject_normalized, confidence)
        VALUES (?, ?, ?)
        """,
        (record.thread_hint, record.subject.lower(), "medium"),
    )
    row = connection.execute(
        "SELECT id FROM threads WHERE thread_key = ?",
        (record.thread_hint,),
    ).fetchone()
    return int(row["id"])


def _insert_message(
    connection: sqlite3.Connection,
    record: "IndexRecord",
    mailbox_id: int,
    thread_id: int,
) -> int:
    connection.execute(
        """
        INSERT INTO messages (
          message_id, thread_id, mailbox_id, subject, sent_at,
          has_attachments, locator_export_id, locator_uid
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.message_id,
            thread_id,
            mailbox_id,
            record.subject,
            record.sent_at,
            1 if record.has_attachments else 0,
            record.locator_export_id,
            record.locator_uid,
        ),
    )
    row = connection.execute(
        "SELECT id FROM messages WHERE locator_export_id = ?",
        (record.locator_export_id,),
    ).fetchone()
    return int(row["id"])


def _ensure_participant(connection: sqlite3.Connection, email: str) -> int:
    parts = email.split("<")
    if len(parts) == 2:
        display_name = parts[0].strip().strip('"')
        addr = parts[1].rstrip(">").strip()
    else:
        display_name = None
        addr = email.strip()

    connection.execute(
        "INSERT OR IGNORE INTO participants (email, display_name) VALUES (?, ?)",
        (addr, display_name or None),
    )
    row = connection.execute(
        "SELECT id FROM participants WHERE email = ?", (addr,)
    ).fetchone()
    return int(row["id"])


def _insert_participants(
    connection: sqlite3.Connection, record: "IndexRecord", message_db_id: int
) -> None:
    for email in [record.sender]:
        pid = _ensure_participant(connection, email)
        connection.execute(
            "INSERT OR IGNORE INTO message_participants (message_id, participant_id, role) VALUES (?, ?, ?)",
            (message_db_id, pid, "from"),
        )
    for email in record.recipients:
        pid = _ensure_participant(connection, email)
        connection.execute(
            "INSERT OR IGNORE INTO message_participants (message_id, participant_id, role) VALUES (?, ?, ?)",
            (message_db_id, pid, "to"),
        )
    for email in record.cc:
        pid = _ensure_participant(connection, email)
        connection.execute(
            "INSERT OR IGNORE INTO message_participants (message_id, participant_id, role) VALUES (?, ?, ?)",
            (message_db_id, pid, "cc"),
        )


def _insert_labels(
    connection: sqlite3.Connection, record: "IndexRecord", message_db_id: int
) -> None:
    for name in record.labels:
        connection.execute("INSERT OR IGNORE INTO labels (name) VALUES (?)", (name,))
        label_row = connection.execute(
            "SELECT id FROM labels WHERE name = ?", (name,)
        ).fetchone()
        connection.execute(
            "INSERT OR IGNORE INTO message_labels (message_id, label_id) VALUES (?, ?)",
            (message_db_id, label_row["id"]),
        )


def _insert_flags(
    connection: sqlite3.Connection, record: "IndexRecord", message_db_id: int
) -> None:
    for name in record.flags:
        connection.execute("INSERT OR IGNORE INTO flags (name) VALUES (?)", (name,))
        flag_row = connection.execute(
            "SELECT id FROM flags WHERE name = ?", (name,)
        ).fetchone()
        connection.execute(
            "INSERT OR IGNORE INTO message_flags (message_id, flag_id) VALUES (?, ?)",
            (message_db_id, flag_row["id"]),
        )


def _insert_relationships(
    connection: sqlite3.Connection, record: "IndexRecord", message_db_id: int
) -> None:
    for ref in record.references:
        connection.execute(
            """
            INSERT OR IGNORE INTO message_relationships
              (message_id, related_message_id, relationship)
            VALUES (?, ?, ?)
            """,
            (message_db_id, ref, "references"),
        )
    if record.in_reply_to:
        connection.execute(
            """
            INSERT OR IGNORE INTO message_relationships
              (message_id, related_message_id, relationship)
            VALUES (?, ?, ?)
            """,
            (message_db_id, record.in_reply_to, "in-reply-to"),
        )


def _insert_attachments(
    connection: sqlite3.Connection, record: "IndexRecord", message_db_id: int
) -> None:
    for att in record.attachments:
        connection.execute(
            """
            INSERT INTO attachments
              (message_id, filename, content_type, size_bytes, content_id, inline_flag)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                message_db_id,
                att.filename,
                att.content_type,
                att.size_bytes,
                att.content_id,
                1 if att.inline_flag else 0,
            ),
        )


def search_messages(
    connection: sqlite3.Connection,
    *,
    sender: str | None = None,
    subject_keyword: str | None = None,
    folder: str | None = None,
    has_attachments: bool | None = None,
    attachment_name_contains: str | None = None,
    attachment_mime_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    thread_key: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search index records with optional filters. Returns dicts with MailPlus locators."""

    clauses: list[str] = []
    params: list[object] = []

    if sender:
        clauses.append("p.email LIKE ?")
        params.append(f"%{sender}%")
    if subject_keyword:
        clauses.append("m.subject LIKE ?")
        params.append(f"%{subject_keyword}%")
    if folder:
        clauses.append("mb.folder_path LIKE ?")
        params.append(f"%{folder}%")
    if has_attachments is not None:
        clauses.append("m.has_attachments = ?")
        params.append(1 if has_attachments else 0)
    if date_from:
        clauses.append("m.sent_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("m.sent_at <= ?")
        params.append(date_to)
    if thread_key:
        clauses.append("t.thread_key = ?")
        params.append(thread_key)

    need_attachment_join = attachment_name_contains or attachment_mime_type
    attachment_clauses: list[str] = []
    if attachment_name_contains:
        attachment_clauses.append("a.filename LIKE ?")
        params.append(f"%{attachment_name_contains}%")
    if attachment_mime_type:
        attachment_clauses.append("a.content_type = ?")
        params.append(attachment_mime_type)

    where = ""
    if clauses or attachment_clauses:
        all_clauses = clauses + attachment_clauses
        where = "WHERE " + " AND ".join(all_clauses)

    attachment_join = ""
    if need_attachment_join:
        attachment_join = "JOIN attachments a ON a.message_id = m.id"

    sender_join = ""
    if sender:
        sender_join = "JOIN message_participants mp ON mp.message_id = m.id AND mp.role = 'from' JOIN participants p ON p.id = mp.participant_id"
    else:
        sender_join = "LEFT JOIN message_participants mp ON mp.message_id = m.id AND mp.role = 'from' LEFT JOIN participants p ON p.id = mp.participant_id"

    sql = f"""
        SELECT DISTINCT m.message_id, m.subject, m.sent_at, m.has_attachments,
               m.locator_export_id, m.locator_uid,
               mb.account, mb.mailbox, mb.folder_path,
               t.thread_key
        FROM messages m
        JOIN mailboxes mb ON mb.id = m.mailbox_id
        LEFT JOIN threads t ON t.id = m.thread_id
        {sender_join}
        {attachment_join}
        {where}
        ORDER BY m.sent_at DESC
        LIMIT ?
    """
    params.append(limit)

    rows = connection.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
