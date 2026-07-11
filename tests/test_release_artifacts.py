"""Tests for release archive resource validation."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


REQUIRED_MIGRATIONS = (
    "001_metadata_schema_v0.sql",
    "002_attachment_metadata.sql",
    "003_cache_and_queue.sql",
)
VALIDATOR = Path(__file__).resolve().parents[1] / "scripts" / "release" / "validate_artifacts.py"


def _write_wheel(path: Path, migrations: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, mode="w") as archive:
        for migration in migrations:
            archive.writestr(
                f"mailplus_intelligence/migrations/{migration}",
                "PRAGMA user_version = 1;\n",
            )


def _write_sdist(path: Path, migrations: tuple[str, ...]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for migration in migrations:
            content = b"PRAGMA user_version = 1;\n"
            member = tarfile.TarInfo(
                f"mailplus_intelligence-0.1.1/src/mailplus_intelligence/migrations/{migration}"
            )
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))


class ReleaseArtifactValidationTests(unittest.TestCase):
    def _run_validator(self, *artifacts: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *(str(path) for path in artifacts)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_accepts_wheel_and_sdist_with_all_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "mailplus_intelligence-0.1.1-py3-none-any.whl"
            sdist = Path(temporary) / "mailplus_intelligence-0.1.1.tar.gz"
            _write_wheel(wheel, REQUIRED_MIGRATIONS)
            _write_sdist(sdist, REQUIRED_MIGRATIONS)

            completed = self._run_validator(wheel, sdist)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(wheel.name, completed.stdout)
            self.assertIn(sdist.name, completed.stdout)

    def test_rejects_wheel_or_sdist_with_a_missing_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for suffix, writer in (("whl", _write_wheel), ("tar.gz", _write_sdist)):
                with self.subTest(suffix=suffix):
                    artifact = Path(temporary) / f"mailplus_intelligence-0.1.1.{suffix}"
                    writer(artifact, REQUIRED_MIGRATIONS[:-1])

                    completed = self._run_validator(artifact)

                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("missing required migration resources", completed.stderr)
                    self.assertIn("003_cache_and_queue.sql", completed.stderr)


if __name__ == "__main__":
    unittest.main()
