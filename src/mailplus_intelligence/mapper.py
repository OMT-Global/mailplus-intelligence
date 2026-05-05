"""Normalize synthetic fixture messages into index-ready records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizationIssue:
    """Mapper issue that can be surfaced without raw body content."""

    fixture_id: str
    code: str
    message: str


@dataclass(frozen=True)
class IndexRecord:
    """Index-ready metadata record derived from a fixture message."""

    fixture_id: str
    message_id: str
    thread_hint: str
    subject: str
    sent_at: str
    sender: str
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    mailbox: str
    folder_path: str
    labels: tuple[str, ...]
    flags: tuple[str, ...]
    references: tuple[str, ...]
    in_reply_to: str | None
    has_attachments: bool
    attachment_count: int
    locator_account: str
    locator_mailbox: str
    locator_folder: str
    locator_uid: str
    locator_export_id: str


@dataclass(frozen=True)
class MapperResult:
    """Result of mapping fixture messages."""

    records: tuple[IndexRecord, ...]
    issues: tuple[NormalizationIssue, ...]


def _reference_values(value: Any) -> tuple[tuple[Any, ...], bool]:
    """Return iterable reference values plus whether the shape was malformed."""

    if value is None:
        return (), True
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return (), True
    return tuple(value), False


def map_fixture_messages(messages: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> MapperResult:
    """Map fixture messages into normalized records and non-fatal issues."""

    records: list[IndexRecord] = []
    issues: list[NormalizationIssue] = []
    seen_message_ids: dict[str, str] = {}

    for message in messages:
        fixture_id = str(message.get("fixture_id", "<unknown>"))
        required_fields = ("message_id", "subject", "from", "date", "mailbox", "folder", "locator")
        missing = [field for field in required_fields if not message.get(field)]
        if missing:
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "missing_required",
                    f"missing required fields: {', '.join(missing)}",
                )
            )
            continue

        message_id = str(message["message_id"])
        if message_id in seen_message_ids:
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "duplicate_message_id",
                    f"duplicates {seen_message_ids[message_id]}",
                )
            )
        else:
            seen_message_ids[message_id] = fixture_id

        reference_values, malformed_reference_shape = _reference_values(message.get("references", ()))
        references = tuple(
            reference
            for reference in (str(value).strip() for value in reference_values)
            if reference.startswith("<") and reference.endswith(">")
        )
        if malformed_reference_shape or len(references) != len(reference_values):
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "malformed_reference",
                    "ignored malformed optional reference values",
                )
            )

        in_reply_to_value = str(message.get("in_reply_to") or "").strip()
        in_reply_to = (
            in_reply_to_value
            if in_reply_to_value.startswith("<") and in_reply_to_value.endswith(">")
            else None
        )

        locator = message["locator"]
        attachments = tuple(message.get("attachments", ()))
        records.append(
            IndexRecord(
                fixture_id=fixture_id,
                message_id=message_id,
                thread_hint=str(message.get("thread_hint") or message_id),
                subject=str(message["subject"]),
                sent_at=str(message["date"]),
                sender=str(message["from"]),
                recipients=tuple(message.get("to", ())),
                cc=tuple(message.get("cc", ())),
                mailbox=str(message["mailbox"]),
                folder_path=str(message["folder"]),
                labels=tuple(message.get("labels", ())),
                flags=tuple(message.get("flags", ())),
                references=references,
                in_reply_to=in_reply_to,
                has_attachments=bool(attachments),
                attachment_count=len(attachments),
                locator_account=str(locator.get("account", "")),
                locator_mailbox=str(locator.get("mailbox", "")),
                locator_folder=str(locator.get("folder", "")),
                locator_uid=str(locator.get("uid", "")),
                locator_export_id=str(locator.get("export_id", "")),
            )
        )

    return MapperResult(tuple(records), tuple(issues))
