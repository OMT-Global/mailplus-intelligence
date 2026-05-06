"""Tests for live_adapter.py gate and stub behaviour."""

from __future__ import annotations

import os
import unittest

from mailplus_intelligence.live_adapter import (
    LiveAdapterNotConfigured,
    fetch_batch,
    load_live_config,
)


class LiveAdapterConfigTests(unittest.TestCase):
    def test_raises_when_env_absent(self) -> None:
        for var in ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN"):
            os.environ.pop(var, None)
        with self.assertRaises(LiveAdapterNotConfigured):
            load_live_config()

    def test_loads_config_from_env(self) -> None:
        os.environ["MAILPLUS_HOST"] = "imap.example.com"
        os.environ["MAILPLUS_USER"] = "user@example.com"
        os.environ["MAILPLUS_TOKEN"] = "secret"
        try:
            config = load_live_config()
            self.assertEqual(config.host, "imap.example.com")
            self.assertEqual(config.user, "user@example.com")
            self.assertEqual(config.token, "secret")
            self.assertEqual(config.mailbox, "INBOX")
            self.assertEqual(config.page_size, 50)
        finally:
            for var in ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN"):
                os.environ.pop(var, None)

    def test_optional_env_overrides(self) -> None:
        os.environ["MAILPLUS_HOST"] = "imap.example.com"
        os.environ["MAILPLUS_USER"] = "user@example.com"
        os.environ["MAILPLUS_TOKEN"] = "secret"
        os.environ["MAILPLUS_MAILBOX"] = "Sent"
        os.environ["MAILPLUS_PAGE_SIZE"] = "25"
        try:
            config = load_live_config()
            self.assertEqual(config.mailbox, "Sent")
            self.assertEqual(config.page_size, 25)
        finally:
            for var in ("MAILPLUS_HOST", "MAILPLUS_USER", "MAILPLUS_TOKEN",
                        "MAILPLUS_MAILBOX", "MAILPLUS_PAGE_SIZE"):
                os.environ.pop(var, None)


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
