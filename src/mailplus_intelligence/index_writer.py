"""Write normalized IndexRecords into the SQLite metadata store."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mapper import AttachmentRecord

if TYPE_CHECKING:
    from .mapper import IndexRecord


@dataclass(frozen=True)
class WriteResult:
    """Summary of a batch index write."""

    inserted: int
    updated: int
    unchanged: int
    failed: int
    errors: tuple[str, ...]

    @property
    def skipped(self) -> int:
        """Compatibility alias for callers that previously reported skips."""

        return self.unchanged

    @property
    def accounted(self) -> int:
        """Number of normalized records represented by the outcome counts."""

        return self.inserted + self.updated + self.unchanged + self.failed


@dataclass(frozen=True)
class _RecordState:
    """Canonical persisted shape used for update and dry-run planning."""

    message_id: str
    thread_key: str
    subject: str
    sent_at: str
    has_attachments: bool
    locator_export_id: str
    locator_uid: str
    account: str
    mailbox: str
    folder_path: str
    participants: tuple[tuple[str, str], ...]
    labels: tuple[str, ...]
    flags: tuple[str, ...]
    relationships: tuple[tuple[str, str], ...]
    attachments: tuple[tuple[str, str, int, str | None, bool], ...]

    @property
    def mailbox_uid_identity(self) -> tuple[str, str, str, str]:
        return (self.account, self.mailbox, self.folder_path, self.locator_uid)


@dataclass(frozen=True)
class _RecordPlan:
    record: "IndexRecord"
    action: str
    error: str | None = None


def _participant_address(value: str) -> str:
    parts = value.split("<")
    if len(parts) == 2:
        return parts[1].rstrip(">").strip()
    return value.strip()


def _attachment_sort_key(
    attachment: tuple[str, str, int, str | None, bool],
) -> tuple[str, str, int, str, bool]:
    return (
        attachment[0],
        attachment[1],
        attachment[2],
        attachment[3] or "",
        attachment[4],
    )


def _validate_record(record: "IndexRecord") -> str | None:
    """Return a privacy-safe validation error before any record mutation."""

    problems: list[str] = []
    required_strings = (
        ("fixture_id", record.fixture_id),
        ("message_id", record.message_id),
        ("thread_hint", record.thread_hint),
        ("subject", record.subject),
        ("sent_at", record.sent_at),
        ("sender", record.sender),
        ("mailbox", record.mailbox),
        ("folder_path", record.folder_path),
        ("locator_account", record.locator_account),
        ("locator_mailbox", record.locator_mailbox),
        ("locator_folder", record.locator_folder),
        ("locator_uid", record.locator_uid),
        ("locator_export_id", record.locator_export_id),
    )
    for field, value in required_strings:
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{field} is required")

    if record.mailbox != record.locator_mailbox:
        problems.append("mailbox and locator_mailbox must match")
    if record.folder_path != record.locator_folder:
        problems.append("folder_path and locator_folder must match")

    for field, values in (
        ("recipients", record.recipients),
        ("cc", record.cc),
        ("labels", record.labels),
        ("flags", record.flags),
        ("references", record.references),
    ):
        if not isinstance(values, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            problems.append(f"{field} must contain non-empty strings")

    if record.in_reply_to is not None and (
        not isinstance(record.in_reply_to, str) or not record.in_reply_to.strip()
    ):
        problems.append("in_reply_to must be a non-empty string or null")
    if not isinstance(record.has_attachments, bool):
        problems.append("has_attachments must be boolean")
    if not isinstance(record.attachments, tuple):
        problems.append("attachments must be a tuple")
    else:
        if record.attachment_count != len(record.attachments):
            problems.append("attachment_count does not match attachments")
        if record.has_attachments != bool(record.attachments):
            problems.append("has_attachments does not match attachments")
        for attachment in record.attachments:
            if not isinstance(attachment, AttachmentRecord):
                problems.append("attachments must contain AttachmentRecord values")
                continue
            if not isinstance(attachment.filename, str):
                problems.append("attachment filename must be a string")
            if not isinstance(attachment.content_type, str):
                problems.append("attachment content_type must be a string")
            if (
                isinstance(attachment.size_bytes, bool)
                or not isinstance(attachment.size_bytes, int)
                or attachment.size_bytes < 0
            ):
                problems.append("attachment size_bytes must be non-negative")
            if attachment.content_id is not None and not isinstance(
                attachment.content_id, str
            ):
                problems.append("attachment content_id must be a string or null")
            if not isinstance(attachment.inline_flag, bool):
                problems.append("attachment inline_flag must be boolean")

    if problems:
        return f"{record.fixture_id}: invalid normalized record: {'; '.join(problems)}"
    return None


def _state_from_record(record: "IndexRecord") -> _RecordState:
    participants = {("from", _participant_address(record.sender))}
    participants.update(
        ("to", _participant_address(value)) for value in record.recipients
    )
    participants.update(("cc", _participant_address(value)) for value in record.cc)

    relationships = {("references", value) for value in record.references}
    if record.in_reply_to:
        relationships.add(("in-reply-to", record.in_reply_to))

    attachments = tuple(
        sorted(
            (
                (
                    attachment.filename,
                    attachment.content_type,
                    attachment.size_bytes,
                    attachment.content_id,
                    attachment.inline_flag,
                )
                for attachment in record.attachments
            ),
            key=_attachment_sort_key,
        )
    )
    return _RecordState(
        message_id=record.message_id,
        thread_key=record.thread_hint,
        subject=record.subject,
        sent_at=record.sent_at,
        has_attachments=record.has_attachments,
        locator_export_id=record.locator_export_id,
        locator_uid=record.locator_uid,
        account=record.locator_account,
        mailbox=record.locator_mailbox,
        folder_path=record.folder_path,
        participants=tuple(sorted(participants)),
        labels=tuple(sorted(set(record.labels))),
        flags=tuple(sorted(set(record.flags))),
        relationships=tuple(sorted(relationships)),
        attachments=attachments,
    )


def _load_record_state(
    connection: sqlite3.Connection, locator_export_id: str
) -> tuple[int, _RecordState] | None:
    row = connection.execute(
        """
        SELECT m.id, m.message_id, m.subject, m.sent_at, m.has_attachments,
               m.locator_export_id, m.locator_uid, t.thread_key,
               mb.account, mb.mailbox, mb.folder_path
        FROM messages m
        JOIN mailboxes mb ON mb.id = m.mailbox_id
        LEFT JOIN threads t ON t.id = m.thread_id
        WHERE m.locator_export_id = ?
        """,
        (locator_export_id,),
    ).fetchone()
    if row is None:
        return None

    message_db_id = int(row["id"])
    participants = tuple(
        (str(item["role"]), str(item["email"]))
        for item in connection.execute(
            """
            SELECT mp.role, p.email
            FROM message_participants mp
            JOIN participants p ON p.id = mp.participant_id
            WHERE mp.message_id = ?
            ORDER BY mp.role, p.email
            """,
            (message_db_id,),
        ).fetchall()
    )
    labels = tuple(
        str(item["name"])
        for item in connection.execute(
            """
            SELECT l.name
            FROM message_labels ml
            JOIN labels l ON l.id = ml.label_id
            WHERE ml.message_id = ?
            ORDER BY l.name
            """,
            (message_db_id,),
        ).fetchall()
    )
    flags = tuple(
        str(item["name"])
        for item in connection.execute(
            """
            SELECT f.name
            FROM message_flags mf
            JOIN flags f ON f.id = mf.flag_id
            WHERE mf.message_id = ?
            ORDER BY f.name
            """,
            (message_db_id,),
        ).fetchall()
    )
    relationships = tuple(
        (str(item["relationship"]), str(item["related_message_id"]))
        for item in connection.execute(
            """
            SELECT relationship, related_message_id
            FROM message_relationships
            WHERE message_id = ?
            ORDER BY relationship, related_message_id
            """,
            (message_db_id,),
        ).fetchall()
    )
    attachments = tuple(
        (
            str(item["filename"]),
            str(item["content_type"]),
            int(item["size_bytes"]),
            str(item["content_id"]) if item["content_id"] is not None else None,
            bool(item["inline_flag"]),
        )
        for item in connection.execute(
            """
            SELECT filename, content_type, size_bytes, content_id, inline_flag
            FROM attachments
            WHERE message_id = ?
            ORDER BY filename, content_type, size_bytes, content_id, inline_flag
            """,
            (message_db_id,),
        ).fetchall()
    )
    return message_db_id, _RecordState(
        message_id=str(row["message_id"]),
        thread_key=str(row["thread_key"] or ""),
        subject=str(row["subject"]),
        sent_at=str(row["sent_at"]),
        has_attachments=bool(row["has_attachments"]),
        locator_export_id=str(row["locator_export_id"]),
        locator_uid=str(row["locator_uid"]),
        account=str(row["account"]),
        mailbox=str(row["mailbox"]),
        folder_path=str(row["folder_path"]),
        participants=participants,
        labels=labels,
        flags=flags,
        relationships=relationships,
        attachments=attachments,
    )


def _mailbox_uid_owner(
    connection: sqlite3.Connection, identity: tuple[str, str, str, str]
) -> str | None:
    row = connection.execute(
        """
        SELECT m.locator_export_id
        FROM messages m
        JOIN mailboxes mb ON mb.id = m.mailbox_id
        WHERE mb.account = ? AND mb.mailbox = ? AND mb.folder_path = ?
          AND m.locator_uid = ?
        """,
        identity,
    ).fetchone()
    return str(row["locator_export_id"]) if row is not None else None


def _plan_records(
    connection: sqlite3.Connection, records: tuple["IndexRecord", ...]
) -> tuple[_RecordPlan, ...]:
    """Classify every record without mutating the database."""

    plans: list[_RecordPlan] = []
    states: dict[str, tuple[int | None, _RecordState] | None] = {}
    owners: dict[tuple[str, str, str, str], str | None] = {}

    for record in records:
        validation_error = _validate_record(record)
        if validation_error is not None:
            plans.append(_RecordPlan(record, "failed", validation_error))
            continue

        desired = _state_from_record(record)
        export_id = desired.locator_export_id
        if export_id not in states:
            states[export_id] = _load_record_state(connection, export_id)
        existing = states[export_id]

        identity = desired.mailbox_uid_identity
        if identity not in owners:
            owners[identity] = _mailbox_uid_owner(connection, identity)
        owner = owners[identity]
        if owner is not None and owner != export_id:
            plans.append(
                _RecordPlan(
                    record,
                    "failed",
                    (
                        f"{record.fixture_id}: mailbox/UID constraint conflicts "
                        "with a different locator_export_id"
                    ),
                )
            )
            continue

        if existing is None:
            action = "inserted"
            message_db_id = None
        else:
            message_db_id, current = existing
            action = "unchanged" if current == desired else "updated"
            if current.mailbox_uid_identity != identity:
                owners[current.mailbox_uid_identity] = None

        states[export_id] = (message_db_id, desired)
        owners[identity] = export_id
        plans.append(_RecordPlan(record, action))

    return tuple(plans)


def _summarize_plans(plans: tuple[_RecordPlan, ...]) -> WriteResult:
    inserted = sum(plan.action == "inserted" for plan in plans)
    updated = sum(plan.action == "updated" for plan in plans)
    unchanged = sum(plan.action == "unchanged" for plan in plans)
    errors = tuple(plan.error for plan in plans if plan.error is not None)
    return WriteResult(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        failed=len(errors),
        errors=errors,
    )


def write_index_records(
    connection: sqlite3.Connection,
    records: tuple["IndexRecord", ...],
    *,
    dry_run: bool = False,
    commit: bool = True,
) -> WriteResult:
    """Plan and write IndexRecords into the SQLite metadata store.

    ``locator_export_id`` is the sole idempotency identity. Matching records are
    unchanged only when their complete normalized metadata matches; otherwise
    they are updated. Each mutation is protected by a savepoint so a child-row
    failure cannot leave a partial parent record. Dry-run executes the same
    validation and planning without issuing mutations.
    """
    plans = _plan_records(connection, records)

    if dry_run:
        return _summarize_plans(plans)

    inserted = 0
    updated = 0
    unchanged = 0
    failed = 0
    errors: list[str] = []

    if not connection.in_transaction:
        connection.execute("BEGIN")

    for index, plan in enumerate(plans):
        if plan.error is not None:
            failed += 1
            errors.append(plan.error)
            continue
        if plan.action == "unchanged":
            unchanged += 1
            continue

        savepoint = f"index_record_{index}"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            if plan.action == "inserted":
                _insert_record(connection, plan.record)
            else:
                _update_record(connection, plan.record)
        except Exception as exc:
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            failed += 1
            errors.append(f"{plan.record.fixture_id}: {exc}")
        else:
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            if plan.action == "inserted":
                inserted += 1
            else:
                updated += 1

    if commit:
        connection.commit()
    return WriteResult(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        failed=failed,
        errors=tuple(errors),
    )


def _insert_record(connection: sqlite3.Connection, record: "IndexRecord") -> None:
    mailbox_id = _ensure_mailbox(connection, record)
    thread_id = _ensure_thread(connection, record)
    message_id = _insert_message(connection, record, mailbox_id, thread_id)
    _insert_participants(connection, record, message_id)
    _insert_labels(connection, record, message_id)
    _insert_flags(connection, record, message_id)
    _insert_relationships(connection, record, message_id)
    _insert_attachments(connection, record, message_id)


def _update_record(connection: sqlite3.Connection, record: "IndexRecord") -> None:
    row = connection.execute(
        "SELECT id FROM messages WHERE locator_export_id = ?",
        (record.locator_export_id,),
    ).fetchone()
    if row is None:
        raise sqlite3.IntegrityError("idempotency identity disappeared before update")

    message_db_id = int(row["id"])
    mailbox_id = _ensure_mailbox(connection, record)
    thread_id = _ensure_thread(connection, record)
    connection.execute(
        """
        UPDATE messages
        SET message_id = ?, thread_id = ?, mailbox_id = ?, subject = ?, sent_at = ?,
            has_attachments = ?, locator_uid = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            record.message_id,
            thread_id,
            mailbox_id,
            record.subject,
            record.sent_at,
            1 if record.has_attachments else 0,
            record.locator_uid,
            message_db_id,
        ),
    )
    for table in (
        "message_participants",
        "message_labels",
        "message_flags",
        "message_relationships",
        "attachments",
    ):
        connection.execute(
            f"DELETE FROM {table} WHERE message_id = ?", (message_db_id,)
        )
    _insert_participants(connection, record, message_db_id)
    _insert_labels(connection, record, message_db_id)
    _insert_flags(connection, record, message_db_id)
    _insert_relationships(connection, record, message_db_id)
    _insert_attachments(connection, record, message_db_id)


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
