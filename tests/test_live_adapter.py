"""Tests for live_adapter.py gate and stub behaviour."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from mailplus_intelligence.live_adapter import (
    LiveAuthenticationError,
    LiveCursorInvalidated,
    LiveAdapterNotConfigured,
    LiveAdapterConfig,
    fetch_batch,
    load_live_config,
)


class LiveAdapterConfigTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_raises_when_env_absent(self) -> None:
        with self.assertRaisesRegex(
            LiveAdapterNotConfigured,
            "Export these process environment variables before retrying",
        ):
            load_live_config()

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": "private-host.example.invalid",
            "MAILPLUS_USER": "private-user@example.invalid",
        },
        clear=True,
    )
    def test_missing_variable_error_does_not_echo_configured_values(self) -> None:
        with self.assertRaises(LiveAdapterNotConfigured) as raised:
            load_live_config()

        message = str(raised.exception)
        self.assertIn("MAILPLUS_TOKEN", message)
        self.assertNotIn("private-host.example.invalid", message)
        self.assertNotIn("private-user@example.invalid", message)

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": "imap.example.com",
            "MAILPLUS_USER": "user@example.com",
            "MAILPLUS_TOKEN": "synthetic-token",
        },
        clear=True,
    )
    def test_loads_config_from_env(self) -> None:
        config = load_live_config()
        self.assertEqual(config.host, "imap.example.com")
        self.assertEqual(config.user, "user@example.com")
        self.assertEqual(config.token, "synthetic-token")
        self.assertEqual(config.mailbox, "INBOX")
        self.assertEqual(config.page_size, 50)

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": "imap.example.com",
            "MAILPLUS_USER": "user@example.com",
            "MAILPLUS_TOKEN": "synthetic-token",
            "MAILPLUS_MAILBOX": "Sent",
            "MAILPLUS_PAGE_SIZE": "25",
        },
        clear=True,
    )
    def test_optional_env_overrides(self) -> None:
        config = load_live_config()
        self.assertEqual(config.mailbox, "Sent")
        self.assertEqual(config.page_size, 25)

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": "imap.example.com",
            "MAILPLUS_USER": "user@example.com",
            "MAILPLUS_TOKEN": "synthetic-token",
            "MAILPLUS_PAGE_SIZE": "unbounded",
        },
        clear=True,
    )
    def test_invalid_page_size_has_an_actionable_redacted_error(self) -> None:
        with self.assertRaisesRegex(
            LiveAdapterNotConfigured,
            "MAILPLUS_PAGE_SIZE must be an integer from 1 through 1000",
        ) as raised:
            load_live_config()
        self.assertNotIn("synthetic-token", str(raised.exception))

    @mock.patch.dict(
        os.environ,
        {
            "MAILPLUS_HOST": " imap.example.com ",
            "MAILPLUS_USER": " user@example.com ",
            "MAILPLUS_TOKEN": " synthetic-token ",
            "MAILPLUS_MAILBOX": "   ",
        },
        clear=True,
    )
    def test_empty_mailbox_is_rejected_without_echoing_credentials(self) -> None:
        with self.assertRaisesRegex(
            LiveAdapterNotConfigured,
            "MAILPLUS_MAILBOX must contain",
        ) as raised:
            load_live_config()
        self.assertNotIn("synthetic-token", str(raised.exception))


class FakeIMAP:
    def __init__(self, *, uidvalidity: bytes = b"42", login_status: str = "OK") -> None:
        self.uidvalidity = uidvalidity
        self.login_status = login_status
        self.fetch_arguments: list[tuple] = []

    def login(self, user, password):
        return self.login_status, [b"ok"]

    def select(self, mailbox, readonly=False):
        self.readonly = readonly
        return "OK", [b"2"]

    def response(self, code):
        return "OK", [self.uidvalidity]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [b"10 11"]
        self.fetch_arguments.append((command, *args))
        uid = args[0]
        headers = (
            f"Message-ID: <imap-{uid}@example.test>\r\n"
            "Subject: Read-only metadata\r\n"
            "From: sender@example.test\r\n"
            "To: recipient@example.test\r\n"
            "Date: Mon, 05 Jan 2026 14:00:00 +0000\r\n\r\n"
        ).encode()
        return "OK", [(b"11 (FLAGS (\\Seen \\Flagged))", headers)]

    def logout(self):
        return "BYE", [b"done"]


class LiveAdapterIMAPTests(unittest.TestCase):
    def _make_config(self):
        return LiveAdapterConfig(host="imap.example.com", user="u@example.com", token="t")

    def test_fetches_headers_only_and_builds_uidvalidity_cursor(self) -> None:
        fake = FakeIMAP()
        batch = fetch_batch(self._make_config(), client_factory=lambda *_: fake)
        self.assertTrue(fake.readonly)
        self.assertEqual(batch.cursor, "uidvalidity:42;uid:11")
        self.assertEqual(len(batch.messages), 2)
        self.assertEqual(batch.messages[0]["flags"], ["\\Seen", "\\Flagged"])
        self.assertTrue(all("BODY.PEEK[HEADER.FIELDS" in call[2] for call in fake.fetch_arguments))
        self.assertFalse(any("RFC822" in call[2] for call in fake.fetch_arguments))

    def test_uidvalidity_change_fails_closed(self) -> None:
        with self.assertRaises(LiveCursorInvalidated):
            fetch_batch(self._make_config(), "uidvalidity:old;uid:10", client_factory=lambda *_: FakeIMAP())

    def test_authentication_failure_is_typed(self) -> None:
        with self.assertRaises(LiveAuthenticationError):
            fetch_batch(self._make_config(), client_factory=lambda *_: FakeIMAP(login_status="NO"))


if __name__ == "__main__":
    unittest.main()
