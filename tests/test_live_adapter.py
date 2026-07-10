"""Tests for live_adapter.py gate and stub behaviour."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from mailplus_intelligence.live_adapter import (
    LiveAdapterNotConfigured,
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


class LiveAdapterStubTests(unittest.TestCase):
    def _make_config(self):
        from mailplus_intelligence.live_adapter import LiveAdapterConfig
        return LiveAdapterConfig(host="imap.example.com", user="u@example.com", token="t")

    def test_fetch_batch_returns_empty_stub(self) -> None:
        config = self._make_config()
        batch = fetch_batch(config)
        self.assertEqual(batch.messages, ())
        self.assertEqual(batch.source_name, "live:u@example.com")

    def test_fetch_batch_source_name_includes_user(self) -> None:
        config = self._make_config()
        batch = fetch_batch(config, cursor="abc")
        self.assertIn("u@example.com", batch.source_name)


if __name__ == "__main__":
    unittest.main()
