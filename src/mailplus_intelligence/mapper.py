"""Normalize synthetic fixture messages into index-ready records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizationIssue:
    """Mapper issue that can be surfaced without raw body content."""

    fixture_id: str
    code: str
    message: str
    severity: str = "warning"

    @property
    def fatal(self) -> bool:
        """Return whether this issue quarantines the source record."""

        return self.severity == "reject"


@dataclass(frozen=True)
class AttachmentRecord:
    """Metadata for a single attachment — no binary content."""

    filename: str
    content_type: str
    size_bytes: int
    content_id: str | None
    inline_flag: bool


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
    attachments: tuple[AttachmentRecord, ...]
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

    @property
    def warnings(self) -> tuple[NormalizationIssue, ...]:
        """Non-fatal normalization issues for records that remain usable."""

        return tuple(issue for issue in self.issues if not issue.fatal)

    @property
    def rejections(self) -> tuple[NormalizationIssue, ...]:
        """Privacy-safe fatal issues for source records that were quarantined."""

        return tuple(issue for issue in self.issues if issue.fatal)


def _reference_values(value: Any) -> tuple[tuple[Any, ...], bool]:
    """Return iterable reference values plus whether the shape was malformed."""

    if value is None:
        return (), True
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return (), True
    return tuple(value), False


def _metadata_values(value: Any) -> tuple[str, ...] | None:
    """Normalize a metadata collection or return None for a malformed shape."""

    if value is None:
        return ()
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return None
    if any(not isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _attachment_record(metadata: Mapping[str, Any]) -> AttachmentRecord:
    """Validate and normalize one attachment metadata object."""

    filename = metadata.get("filename")
    content_type = metadata.get("content_type")
    size_bytes = metadata.get("size_bytes", 0)
    content_id = metadata.get("content_id")
    inline_flag = metadata.get("inline_flag", False)
    if filename is not None and not isinstance(filename, str):
        raise TypeError("attachment filename is not a string")
    if content_type is not None and not isinstance(content_type, str):
        raise TypeError("attachment content type is not a string")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
        raise TypeError("attachment size is not an integer")
    if content_id is not None and not isinstance(content_id, str):
        raise TypeError("attachment content ID is not a string")
    if not isinstance(inline_flag, bool):
        raise TypeError("attachment inline flag is not boolean")
    return AttachmentRecord(
        filename=filename or "",
        content_type=content_type or "",
        size_bytes=size_bytes,
        content_id=content_id,
        inline_flag=inline_flag,
    )


def map_fixture_messages(
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> MapperResult:
    """Map fixture messages into normalized records, warnings, and rejects."""

    records: list[IndexRecord] = []
    issues: list[NormalizationIssue] = []
    seen_message_ids: dict[str, str] = {}

    for message in messages:
        if not isinstance(message, Mapping):
            issues.append(
                NormalizationIssue(
                    "<unknown>",
                    "invalid_record",
                    "source record is not a metadata object",
                    "reject",
                )
            )
            continue

        fixture_id = str(message.get("fixture_id", "<unknown>"))
        required_fields = (
            "message_id",
            "subject",
            "from",
            "date",
            "mailbox",
            "folder",
            "locator",
        )
        missing = [field for field in required_fields if not message.get(field)]
        if missing:
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "missing_required",
                    f"missing required fields: {', '.join(missing)}",
                    "reject",
                )
            )
            continue

        locator = message["locator"]
        if not isinstance(locator, Mapping):
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "invalid_locator",
                    "locator must be a metadata object",
                    "reject",
                )
            )
            continue

        collection_fields: dict[str, tuple[str, ...]] = {}
        malformed_collection = None
        for field in ("to", "cc", "labels", "flags"):
            values = _metadata_values(message.get(field, ()))
            if values is None:
                malformed_collection = field
                break
            collection_fields[field] = values
        if malformed_collection is not None:
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "invalid_collection",
                    f"{malformed_collection} must be an array",
                    "reject",
                )
            )
            continue

        reference_values, malformed_reference_shape = _reference_values(
            message.get("references", ())
        )
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

        raw_attachment_value = message.get("attachments", ())
        if (
            isinstance(raw_attachment_value, str | bytes)
            or not isinstance(raw_attachment_value, Sequence)
        ):
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "invalid_attachment_metadata",
                    "attachments must be an array of metadata objects",
                    "reject",
                )
            )
            continue

        raw_attachments = tuple(raw_attachment_value)
        try:
            if any(
                not isinstance(attachment, Mapping)
                for attachment in raw_attachments
            ):
                raise TypeError("attachment is not an object")
            attachment_records = tuple(
                _attachment_record(attachment)
                for attachment in raw_attachments
            )
        except (TypeError, ValueError, OverflowError):
            issues.append(
                NormalizationIssue(
                    fixture_id,
                    "invalid_attachment_metadata",
                    "attachment metadata contains an invalid value",
                    "reject",
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

        records.append(
            IndexRecord(
                fixture_id=fixture_id,
                message_id=message_id,
                thread_hint=str(message.get("thread_hint") or message_id),
                subject=str(message["subject"]),
                sent_at=str(message["date"]),
                sender=str(message["from"]),
                recipients=collection_fields["to"],
                cc=collection_fields["cc"],
                mailbox=str(message["mailbox"]),
                folder_path=str(message["folder"]),
                labels=collection_fields["labels"],
                flags=collection_fields["flags"],
                references=references,
                in_reply_to=in_reply_to,
                has_attachments=bool(raw_attachments),
                attachment_count=len(raw_attachments),
                attachments=attachment_records,
                locator_account=str(locator.get("account") or ""),
                locator_mailbox=str(locator.get("mailbox") or ""),
                locator_folder=str(locator.get("folder") or ""),
                locator_uid=str(locator.get("uid") or ""),
                locator_export_id=str(locator.get("export_id") or ""),
            )
        )

    return MapperResult(tuple(records), tuple(issues))
