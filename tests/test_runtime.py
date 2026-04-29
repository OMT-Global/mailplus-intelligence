from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mailplus_intelligence import connect_sqlite, default_runtime_profile


class RuntimeBaselineTests(unittest.TestCase):
    def test_default_runtime_profile_is_python_sqlite_and_non_live(self) -> None:
        profile = default_runtime_profile()

        self.assertEqual(profile.language, "python")
        self.assertEqual(profile.python_version, "3.12")
        self.assertEqual(profile.storage_engine, "sqlite")
        self.assertFalse(profile.live_mailplus_access)

    def test_sqlite_connection_supports_index_style_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "mailplus-intelligence.db"
            connection = connect_sqlite(database)
            try:
                foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
                self.assertEqual(foreign_keys_enabled, 1)

                connection.execute(
                    "CREATE TABLE message_index (message_id TEXT PRIMARY KEY, subject TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO message_index (message_id, subject) VALUES (?, ?)",
                    ("m0@example.test", "M0 runtime baseline"),
                )

                row = connection.execute(
                    "SELECT subject FROM message_index WHERE message_id = ?",
                    ("m0@example.test",),
                ).fetchone()
                self.assertEqual(row["subject"], "M0 runtime baseline")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
