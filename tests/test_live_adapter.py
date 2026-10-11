"""Tests for live_adapter.py gate and stub behaviour."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from mailplus_intelligence.live_adapter import (
    LiveAuthenticationError,
    LiveBackendUnavailable,
    LiveCursorInvalidated,
    LiveAdapterNotConfigured,
    LiveAdapterConfig,
    fetch_batch,
    load_live_config,
)
from mailplus_intelligence.schema import apply_all_migrations
from mailplus_intelligence.sqlite import connect_sqlite
from mailplus_intelligence.sync import get_checkpoint, run_sync_batch


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


class RangeSearchIMAP(FakeIMAP):
    """Model RFC 3501 UID ranges, including reversed ranges at mailbox EOF."""

    def __init__(self, uids, *, fail_uid=None, **kwargs):
        super().__init__(**kwargs)
        self.uids = uids
        self.fail_uid = fail_uid
        self.logged_out = False

    def uid(self, command, *args):
        if command == "search":
            if not self.uids:
                return "OK", [b""]
            start = int(args[1].removeprefix("UID ").split(":")[0])
            lower, upper = sorted((start, max(self.uids)))
            matches = [uid for uid in self.uids if lower <= uid <= upper]
            return "OK", [" ".join(map(str, matches)).encode()]
        if int(args[0]) == self.fail_uid:
            raise OSError("synthetic connection loss")
        return super().uid(command, *args)

    def logout(self):
        self.logged_out = True
        return super().logout()


class LiveAdapterRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LiveAdapterConfig(
            host="imap.example.test", user="user@example.test", token="synthetic"
        )
        self.conn = connect_sqlite(":memory:")
        apply_all_migrations(self.conn)
        self.addCleanup(self.conn.close)

    def sync(self, fake, cursor="", *, config=None):
        batch = fetch_batch(config or self.config, cursor, client_factory=lambda *_: fake)
        result = run_sync_batch(self.conn, batch)
        self.assertTrue(result.success, result.write_errors)
        return batch, result

    def test_caught_up_poll_does_not_reingest_last_message(self) -> None:
        initial, _ = self.sync(RangeSearchIMAP([10, 11]))
        fake = RangeSearchIMAP([10, 11])

        batch, result = self.sync(fake, initial.cursor)

        self.assertEqual(batch.messages, ())
        self.assertEqual(batch.cursor, initial.cursor)
        self.assertEqual(result.accounted, 0)
        self.assertEqual(fake.fetch_arguments, [])
        self.assertTrue(fake.logged_out)

    def test_expunged_tail_does_not_move_checkpoint_backwards(self) -> None:
        initial, _ = self.sync(RangeSearchIMAP([10, 11]))
        fake = RangeSearchIMAP([10])

        batch, _ = self.sync(fake, initial.cursor)

        self.assertEqual(batch.cursor, initial.cursor)
        self.assertEqual(batch.messages, ())
        self.assertEqual(get_checkpoint(self.conn, batch.source_name)["cursor"], initial.cursor)
        self.assertEqual(fake.fetch_arguments, [])

    def test_numeric_pagination_does_not_skip_uids_in_search_response(self) -> None:
        config = LiveAdapterConfig(
            host=self.config.host, user=self.config.user, token=self.config.token, page_size=2
        )
        cursor = ""
        ingested = []
        for _ in range(3):
            batch, _ = self.sync(RangeSearchIMAP([10, 100, 9]), cursor, config=config)
            ingested.extend(message["locator"]["uid"] for message in batch.messages)
            cursor = batch.cursor

        self.assertEqual(ingested, ["9", "10", "100"])
        self.assertEqual(cursor, "uidvalidity:42;uid:100")

    def test_empty_mailbox_preserves_checkpoint(self) -> None:
        initial, _ = self.sync(RangeSearchIMAP([10]))
        batch, result = self.sync(RangeSearchIMAP([]), initial.cursor)
        self.assertEqual(batch.cursor, initial.cursor)
        self.assertEqual(result.accounted, 0)

    def test_partial_fetch_disconnect_keeps_checkpoint_and_retry_recovers(self) -> None:
        initial, _ = self.sync(RangeSearchIMAP([9]))
        fake = RangeSearchIMAP([9, 10, 11], fail_uid=11)
        with self.assertRaises(LiveBackendUnavailable):
            self.sync(fake, initial.cursor)
        self.assertEqual(len(fake.fetch_arguments), 1)
        self.assertTrue(fake.logged_out)
        self.assertEqual(get_checkpoint(self.conn, initial.source_name)["cursor"], initial.cursor)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

        batch, result = self.sync(RangeSearchIMAP([9, 10, 11]), initial.cursor)
        self.assertEqual(result.inserted, 2)
        self.assertEqual(batch.cursor, "uidvalidity:42;uid:11")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 3)
        _, replayed = self.sync(RangeSearchIMAP([9, 10, 11]), initial.cursor)
        self.assertEqual(replayed.inserted, 0)
        self.assertEqual(replayed.unchanged, 2)

    def test_uidvalidity_change_preserves_committed_data_and_checkpoint(self) -> None:
        initial, _ = self.sync(RangeSearchIMAP([10]))
        fake = RangeSearchIMAP([10], uidvalidity=b"43")
        with self.assertRaises(LiveCursorInvalidated):
            self.sync(fake, initial.cursor)
        self.assertTrue(fake.logged_out)
        self.assertEqual(fake.fetch_arguments, [])
        self.assertEqual(get_checkpoint(self.conn, initial.source_name)["cursor"], initial.cursor)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
