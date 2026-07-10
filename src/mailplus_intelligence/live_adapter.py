"""Contract-only live MailPlus adapter stub.

Provides the same ``SyncBatch`` interface as the fixture path. The network
transport is intentionally unimplemented; configuration alone never proves
reachability, authentication, or sync capability.

GATE: This module requires MAILPLUS_HOST, MAILPLUS_USER, and MAILPLUS_TOKEN to
be set in the environment.  It raises ``LiveAdapterNotConfigured`` if any are
missing, so CI (which omits them) will never attempt a live connection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .sync import SyncBatch


LIVE_REQUIRED_ENV_VARS = ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN")
LIVE_OPTIONAL_ENV_VARS = ("MAILPLUS_MAILBOX", "MAILPLUS_PAGE_SIZE")
MAX_MAILBOX_CHARS = 255


class LiveAdapterNotConfigured(RuntimeError):
    """Raised when required environment variables are absent."""


@dataclass(frozen=True)
class LiveAdapterConfig:
    host: str
    user: str
    token: str
    mailbox: str = "INBOX"
    page_size: int = 50


def load_live_config() -> LiveAdapterConfig:
    """Load adapter config from environment variables.

    Required variables:
        MAILPLUS_HOST   — e.g. imap.example.com
        MAILPLUS_USER   — mailbox address
        MAILPLUS_TOKEN  — OAuth2 bearer token or app password
    Optional:
        MAILPLUS_MAILBOX   (default INBOX)
        MAILPLUS_PAGE_SIZE (default 50)
    """
    missing = [
        name
        for name in LIVE_REQUIRED_ENV_VARS
        if not (os.getenv(name) or "").strip()
    ]
    if missing:
        raise LiveAdapterNotConfigured(
            "Live adapter is not configured. Export these process environment "
            f"variables before retrying: {', '.join(missing)}. "
            "Configuration files are not loaded automatically."
        )

    page_size_value = os.getenv("MAILPLUS_PAGE_SIZE", "50").strip()
    try:
        page_size = int(page_size_value)
    except ValueError as exc:
        raise LiveAdapterNotConfigured(
            "MAILPLUS_PAGE_SIZE must be an integer from 1 through 1000. "
            "Export a bounded value before retrying."
        ) from exc
    if not 1 <= page_size <= 1000:
        raise LiveAdapterNotConfigured(
            "MAILPLUS_PAGE_SIZE must be from 1 through 1000. "
            "Export a bounded value before retrying."
        )

    mailbox = os.getenv("MAILPLUS_MAILBOX", "INBOX").strip()
    if not mailbox or len(mailbox) > MAX_MAILBOX_CHARS:
        raise LiveAdapterNotConfigured(
            f"MAILPLUS_MAILBOX must contain from 1 through {MAX_MAILBOX_CHARS} characters. "
            "Export a bounded mailbox name before retrying."
        )

    return LiveAdapterConfig(
        host=os.environ["MAILPLUS_HOST"].strip(),
        user=os.environ["MAILPLUS_USER"].strip(),
        token=os.environ["MAILPLUS_TOKEN"].strip(),
        mailbox=mailbox,
        page_size=page_size,
    )


def fetch_batch(
    config: LiveAdapterConfig,
    cursor: str = "",
) -> SyncBatch:
    """Fetch one page of metadata-only messages from the live account.

    This is a stub — the actual IMAP/MailPlus API integration is out of scope
    for the current phase.  Returns an empty batch so callers can be wired up
    without a live server.

    Replace the body of this function (and the _fetch_messages helper below)
    once the MailPlus API client library is available.
    """
    messages = _fetch_messages(config, cursor)
    new_cursor = messages[-1].get("message_id", cursor) if messages else cursor
    return SyncBatch(
        source_name=f"live:{config.user}",
        cursor=new_cursor,
        messages=tuple(messages),
    )


def _fetch_messages(
    config: LiveAdapterConfig,
    cursor: str,
) -> list[dict[str, Any]]:
    # Stub: replace with live API call.
    return []
