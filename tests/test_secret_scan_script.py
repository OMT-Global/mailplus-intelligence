from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-detect-secrets.sh"


class SecretScanScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir_context = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmpdir_context.name)
        subprocess.run(["git", "init"], cwd=self.workspace, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.workspace,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "MailPlus Test"],
            cwd=self.workspace,
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.tmpdir_context.cleanup()

    def run_scan(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), mode],
            cwd=self.workspace,
            check=False,
            capture_output=True,
            text=True,
        )

    def write_file(self, relative_path: str, content: str) -> Path:
        path = self.workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def git_add(self, *relative_paths: str) -> None:
        subprocess.run(["git", "add", *relative_paths], cwd=self.workspace, check=True)

    def test_staged_mode_scans_staged_files(self) -> None:
        secret_shape = "OPENAI" + "_API_KEY=not-a-real-test-value\n"
        self.write_file("candidate.txt", secret_shape)
        self.git_add("candidate.txt")

        result = self.run_scan("--staged")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OPENAI" + "_API_KEY=", result.stderr)

    def test_local_mode_includes_untracked_non_ignored_files(self) -> None:
        self.write_file("tracked.txt", "ordinary synthetic content\n")
        self.git_add("tracked.txt")
        self.write_file("local/mailplus-export.eml", "From: sender@example.com\n")

        ci_result = self.run_scan("--all-files")
        local_result = self.run_scan("--all-files-with-untracked")
        alias_result = self.run_scan("--all-local")

        self.assertEqual(ci_result.returncode, 0, ci_result.stderr)
        self.assertNotEqual(local_result.returncode, 0)
        self.assertIn("mailplus-export.eml", local_result.stderr)
        self.assertNotEqual(alias_result.returncode, 0)
        self.assertIn("mailplus-export.eml", alias_result.stderr)

    def test_mailplus_link_leak_is_detected(self) -> None:
        live_link = "https://mail.vendor.invalid/reset?" + "token=abc123"
        self.write_file("message.txt", f"Reset at {live_link}\n")
        self.git_add("message.txt")

        result = self.run_scan("--all-files")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MailPlus link leak", result.stderr)

    def test_synthetic_redacted_doc_link_is_allowed(self) -> None:
        self.write_file(
            "docs/example.md",
            "Synthetic reset URL: https://example.com/reset?token=[REDACTED_TOKEN]\n",
        )
        self.git_add("docs/example.md")

        result = self.run_scan("--all-files")

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
