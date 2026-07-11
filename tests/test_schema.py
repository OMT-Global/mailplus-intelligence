from __future__ import annotations

import unittest
from unittest import mock

from mailplus_intelligence import (
    apply_all_migrations,
    apply_schema_v0,
    connect_sqlite,
    current_schema_version,
)


class MetadataSchemaV0Tests(unittest.TestCase):
    def test_all_packaged_migrations_apply_to_an_empty_database(self) -> None:
        connection = connect_sqlite()
        try:
            apply_all_migrations(connection)
            self.assertEqual(current_schema_version(connection), 3)
        finally:
            connection.close()

    def test_missing_migration_resource_has_an_actionable_error(self) -> None:
        with mock.patch("mailplus_intelligence.schema.resources.files") as files:
            files.return_value.joinpath.return_value.read_text.side_effect = FileNotFoundError
            connection = connect_sqlite()
            try:
                with self.assertRaisesRegex(
                    FileNotFoundError,
                    "required migration package resource is missing: migrations/001_metadata_schema_v0.sql",
                ):
                    apply_schema_v0(connection)
            finally:
                connection.close()

    def test_schema_bootstrap_creates_core_tables_and_version(self) -> None:
        connection = connect_sqlite()
        try:
            apply_schema_v0(connection)

            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "mailboxes",
                    "threads",
                    "messages",
                    "participants",
                    "message_participants",
                    "labels",
                    "message_labels",
                    "flags",
                    "message_flags",
                    "attachments",
                    "message_relationships",
                    "sync_checkpoints",
                }.issubset(tables)
            )
            self.assertEqual(current_schema_version(connection), 1)
        finally:
            connection.close()

    def test_schema_supports_message_locator_and_checkpoint_round_trip(self) -> None:
        connection = connect_sqlite()
        try:
            apply_schema_v0(connection)

            connection.execute(
                "INSERT INTO mailboxes (account, mailbox, folder_path) VALUES (?, ?, ?)",
                ("fixture-account", "Inbox", "Projects/Atlas"),
            )
            connection.execute(
                """
                INSERT INTO threads (thread_key, subject_normalized, confidence)
                VALUES (?, ?, ?)
                """,
                ("thread-a", "project atlas kickoff", "high"),
            )
            connection.execute(
                """
                INSERT INTO messages (
                  message_id, thread_id, mailbox_id, subject, sent_at,
                  has_attachments, locator_export_id, locator_uid
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "<thread-a-001@example.test>",
                    1,
                    1,
                    "Project Atlas kickoff",
                    "2026-01-05T14:00:00Z",
                    0,
                    "fixture-export-001",
                    "1001",
                ),
            )
            connection.execute(
                """
                INSERT INTO sync_checkpoints (source_name, cursor, last_success_at)
                VALUES (?, ?, ?)
                """,
                ("fixture-batch", "batch-001", "2026-01-05T14:01:00Z"),
            )

            message = connection.execute(
                """
                SELECT messages.message_id, mailboxes.folder_path, threads.thread_key
                FROM messages
                JOIN mailboxes ON mailboxes.id = messages.mailbox_id
                JOIN threads ON threads.id = messages.thread_id
                WHERE messages.locator_export_id = ?
                """,
                ("fixture-export-001",),
            ).fetchone()
            checkpoint = connection.execute(
                "SELECT cursor FROM sync_checkpoints WHERE source_name = ?",
                ("fixture-batch",),
            ).fetchone()

            self.assertEqual(message["message_id"], "<thread-a-001@example.test>")
            self.assertEqual(message["folder_path"], "Projects/Atlas")
            self.assertEqual(message["thread_key"], "thread-a")
            self.assertEqual(checkpoint["cursor"], "batch-001")
        finally:
            connection.close()

    def test_schema_enforces_foreign_keys(self) -> None:
        connection = connect_sqlite()
        try:
            apply_schema_v0(connection)

            with self.assertRaises(Exception):
                connection.execute(
                    """
                    INSERT INTO messages (
                      message_id, mailbox_id, subject, sent_at,
                      locator_export_id, locator_uid
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "<missing-mailbox@example.test>",
                        999,
                        "Missing mailbox",
                        "2026-01-01T00:00:00Z",
                        "fixture-export-missing",
                        "999",
                    ),
                )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
