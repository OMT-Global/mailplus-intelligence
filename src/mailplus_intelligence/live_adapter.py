"""Live MailPlus adapter stub (#71).

Provides the same SyncBatch interface as the fixture path but reads from a
real MailPlus account via environment-configured credentials.

GATE: This module requires MAILPLUS_HOST, MAILPLUS_USER, and MAILPLUS_TOKEN to
be set in the environment.  It raises ``LiveAdapterNotConfigured`` if any are
missing, so CI (which omits them) will never attempt a live connection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .sync import SyncBatch


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
    missing = [v for v in ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN") if not os.getenv(v)]
    if missing:
        raise LiveAdapterNotConfigured(
            f"Live adapter requires environment variables: {', '.join(missing)}"
        )
    return LiveAdapterConfig(
        host=os.environ["MAILPLUS_HOST"],
        user=os.environ["MAILPLUS_USER"],
        token=os.environ["MAILPLUS_TOKEN"],
        mailbox=os.getenv("MAILPLUS_MAILBOX", "INBOX"),
        page_size=int(os.getenv("MAILPLUS_PAGE_SIZE", "50")),
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
