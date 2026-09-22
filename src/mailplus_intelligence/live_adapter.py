"""Credential-gated, read-only IMAP metadata adapter."""

from __future__ import annotations

import email.utils
import imaplib
import os
import re
import socket
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from typing import Any, Callable, Protocol

from .sync import SyncBatch


LIVE_REQUIRED_ENV_VARS = ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN")
LIVE_OPTIONAL_ENV_VARS = ("MAILPLUS_MAILBOX", "MAILPLUS_PAGE_SIZE", "MAILPLUS_PORT")
MAX_MAILBOX_CHARS = 255


class LiveAdapterError(RuntimeError):
    """Base error for a safe, read-only live adapter operation."""


class LiveAdapterNotConfigured(LiveAdapterError):
    """Raised when required environment variables are absent."""


class LiveAuthenticationError(LiveAdapterError):
    """Raised for an authentication failure without echoing credentials."""


class LiveCursorInvalidated(LiveAdapterError):
    """Raised if a saved mailbox UIDVALIDITY no longer matches."""


class LiveBackendUnavailable(LiveAdapterError):
    """Raised for safe connection, timeout, or protocol availability failures."""


class LiveMetadataMalformed(LiveAdapterError):
    """Raised when IMAP metadata cannot produce a valid source record."""


class _IMAPClient(Protocol):
    def login(self, user: str, password: str) -> tuple[str, list[bytes]]: ...
    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]: ...
    def response(self, code: str) -> tuple[str, list[bytes] | None]: ...
    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]: ...
    def logout(self) -> tuple[str, list[bytes]]: ...


@dataclass(frozen=True)
class LiveAdapterConfig:
    host: str
    user: str
    token: str
    mailbox: str = "INBOX"
    page_size: int = 50
    port: int = 993


def load_live_config(environ: dict[str, str] | None = None) -> LiveAdapterConfig:
    """Load bounded configuration from the invoking process only."""

    values = os.environ if environ is None else environ
    missing = [name for name in LIVE_REQUIRED_ENV_VARS if not (values.get(name) or "").strip()]
    if missing:
        raise LiveAdapterNotConfigured(
            "Live adapter is not configured. Export these process environment "
            f"variables before retrying: {', '.join(missing)}. Configuration files are not loaded automatically."
        )
    try:
        page_size = int(values.get("MAILPLUS_PAGE_SIZE", "50").strip())
    except ValueError as exc:
        raise LiveAdapterNotConfigured("MAILPLUS_PAGE_SIZE must be an integer from 1 through 1000.") from exc
    if not 1 <= page_size <= 1000:
        raise LiveAdapterNotConfigured("MAILPLUS_PAGE_SIZE must be from 1 through 1000.")
    try:
        port = int(values.get("MAILPLUS_PORT", "993").strip())
    except ValueError as exc:
        raise LiveAdapterNotConfigured("MAILPLUS_PORT must be an integer from 1 through 65535.") from exc
    if not 1 <= port <= 65535:
        raise LiveAdapterNotConfigured("MAILPLUS_PORT must be from 1 through 65535.")
    mailbox = values.get("MAILPLUS_MAILBOX", "INBOX").strip()
    if not mailbox or len(mailbox) > MAX_MAILBOX_CHARS:
        raise LiveAdapterNotConfigured(f"MAILPLUS_MAILBOX must contain from 1 through {MAX_MAILBOX_CHARS} characters.")
    return LiveAdapterConfig(values["MAILPLUS_HOST"].strip(), values["MAILPLUS_USER"].strip(), values["MAILPLUS_TOKEN"].strip(), mailbox, page_size, port)


def _parse_cursor(cursor: str) -> tuple[str | None, int]:
    if not cursor:
        return None, 0
    try:
        uidvalidity, uid = cursor.split(";uid:", 1)
        return uidvalidity.removeprefix("uidvalidity:"), int(uid)
    except (ValueError, TypeError) as exc:
        raise LiveCursorInvalidated("saved IMAP cursor is malformed; restart metadata sync explicitly") from exc


def _fetch_flags(metadata: bytes | str) -> list[str]:
    """Extract IMAP flags from the fetch envelope without reading message data."""

    text = metadata.decode("ascii", "replace") if isinstance(metadata, bytes) else metadata
    match = re.search(r"FLAGS \(([^)]*)\)", text)
    return match.group(1).split() if match else []


def _metadata_record(raw_headers: bytes, uid: str, config: LiveAdapterConfig, flags: list[str]) -> dict[str, Any]:
    message = BytesParser(policy=default).parsebytes(raw_headers)
    message_id = str(message.get("Message-ID") or "").strip()
    subject = str(message.get("Subject") or "").strip()
    date = email.utils.parsedate_to_datetime(str(message.get("Date") or ""))
    sender = str(message.get("From") or "").strip()
    if not all((message_id, subject, sender)):
        raise LiveMetadataMalformed("IMAP header response omitted required metadata")
    return {
        "fixture_id": f"imap-{uid}",
        "message_id": message_id,
        "subject": subject,
        "from": sender,
        "to": [item for _, item in email.utils.getaddresses([str(message.get("To") or "")]) if item],
        "cc": [item for _, item in email.utils.getaddresses([str(message.get("Cc") or "")]) if item],
        "date": date.isoformat() if date else str(message.get("Date")),
        "mailbox": config.mailbox,
        "folder": config.mailbox,
        "labels": [],
        "flags": flags,
        "references": str(message.get("References") or "").split(),
        "in_reply_to": str(message.get("In-Reply-To") or "").strip() or None,
        "attachments": [],
        "locator": {"account": config.user, "mailbox": config.mailbox, "folder": config.mailbox, "uid": uid, "export_id": f"imap:{config.mailbox}:{uid}"},
    }


def fetch_batch(config: LiveAdapterConfig, cursor: str = "", *, client_factory: Callable[[str, int], _IMAPClient] | None = None) -> SyncBatch:
    """Fetch one bounded metadata/header page using IMAP read-only semantics."""

    expected_uidvalidity, last_uid = _parse_cursor(cursor)
    factory = client_factory or (lambda host, port: imaplib.IMAP4_SSL(host, port))
    client: _IMAPClient | None = None
    try:
        client = factory(config.host, config.port)
        status, _ = client.login(config.user, config.token)
        if status != "OK":
            raise LiveAuthenticationError("IMAP authentication was rejected")
        status, _ = client.select(config.mailbox, readonly=True)
        if status != "OK":
            raise LiveBackendUnavailable("IMAP mailbox selection failed")
        _, uidvalidity_data = client.response("UIDVALIDITY")
        uidvalidity = (uidvalidity_data or [b""])[0].decode() if uidvalidity_data else ""
        if not uidvalidity:
            raise LiveBackendUnavailable("IMAP server did not provide UIDVALIDITY")
        if expected_uidvalidity and expected_uidvalidity != uidvalidity:
            raise LiveCursorInvalidated("IMAP UIDVALIDITY changed; restart metadata sync explicitly")
        status, matches = client.uid("search", None, f"UID {last_uid + 1}:*")
        if status != "OK":
            raise LiveBackendUnavailable("IMAP UID search failed")
        uids = str(matches[0].decode() if matches else "").split()[: config.page_size]
        records: list[dict[str, Any]] = []
        for uid in uids:
            status, payload = client.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT FROM TO CC DATE REFERENCES IN-REPLY-TO)] FLAGS)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                raise LiveBackendUnavailable("IMAP metadata fetch failed")
            records.append(_metadata_record(payload[0][1], uid, config, _fetch_flags(payload[0][0])))
        next_uid = int(uids[-1]) if uids else last_uid
        return SyncBatch(source_name=f"imap:{config.mailbox}", cursor=f"uidvalidity:{uidvalidity};uid:{next_uid}", messages=tuple(records))
    except imaplib.IMAP4.error as exc:
        raise LiveAuthenticationError("IMAP authentication or command failed") from exc
    except (OSError, socket.timeout) as exc:
        raise LiveBackendUnavailable("IMAP backend is unreachable") from exc
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
