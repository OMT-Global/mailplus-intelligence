"""Tests for the executable operator-documentation contract."""

from __future__ import annotations

import importlib.util
import tempfile
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "docs_smoke.py"
SPEC = importlib.util.spec_from_file_location("mailplus_docs_smoke", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"cannot load {SCRIPT}")
DOCS_SMOKE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOCS_SMOKE
SPEC.loader.exec_module(DOCS_SMOKE)


class DocsSmokeContractTests(unittest.TestCase):
    def test_all_operator_bash_blocks_are_classified(self) -> None:
        blocks = DOCS_SMOKE.load_command_blocks(REPO_ROOT)

        self.assertTrue(any(block.classification == "fixture-smoke" for block in blocks))
        self.assertTrue(
            all(block.classification in DOCS_SMOKE.ALLOWED_CLASSIFICATIONS for block in blocks)
        )

    def test_unclassified_bash_block_has_an_actionable_error(self) -> None:
        with self.assertRaisesRegex(
            DOCS_SMOKE.DocsContractError,
            "Label fixture commands `bash fixture-smoke`",
        ):
            DOCS_SMOKE.parse_command_blocks(
                Path("docs/example.md"),
                "```bash\nmpi doctor\n```\n",
            )

    def test_malformed_alternate_and_empty_shell_blocks_fail_closed(self) -> None:
        invalid_blocks = (
            "```bash fixture-smoke extra\nmpi doctor\n```\n",
            "```sh fixture-smoke\nmpi doctor\n```\n",
            "```bash fixture-smoke\n\n```\n",
        )
        for text in invalid_blocks:
            with self.subTest(text=text), self.assertRaises(DOCS_SMOKE.DocsContractError):
                DOCS_SMOKE.parse_command_blocks(Path("docs/example.md"), text)

    def test_commonmark_indented_and_tilde_bash_fences_are_parsed(self) -> None:
        blocks = DOCS_SMOKE.parse_command_blocks(
            Path("docs/example.md"),
            "   ~~~~bash fixture-smoke\nmpi doctor\n   ~~~~~\n\n"
            "  ```bash live-manual\nmpi sync status\n  ````\n",
        )

        self.assertEqual([block.classification for block in blocks], ["fixture-smoke", "live-manual"])
        self.assertEqual([block.body for block in blocks], ["mpi doctor", "mpi sync status"])

    def test_unclassified_or_unterminated_tilde_shell_fences_fail_closed(self) -> None:
        invalid_blocks = (
            "~~~bash\nmpi doctor\n~~~\n",
            "  ~~~~zsh live-manual\nmpi doctor\n  ~~~~\n",
            " ~~~bash fixture-smoke\nmpi doctor\n",
        )
        for text in invalid_blocks:
            with self.subTest(text=text), self.assertRaises(DOCS_SMOKE.DocsContractError):
                DOCS_SMOKE.parse_command_blocks(Path("docs/example.md"), text)

    def test_container_and_attribute_form_shell_fences_fail_closed(self) -> None:
        unsupported_blocks = (
            "- Run:\n    ```bash fixture-smoke\n    mpi doctor\n    ```\n",
            "- Run:\n ```bash fixture-smoke\n mpi doctor\n ```\n",
            "- Run:\n  ```bash fixture-smoke\n  mpi doctor\n  ```\n",
            "- Run:\n   ```bash fixture-smoke\n   mpi doctor\n   ```\n",
            "1. Run:\n ```bash fixture-smoke\n mpi doctor\n ```\n",
            "1. Run:\n  ```bash fixture-smoke\n  mpi doctor\n  ```\n",
            "1. Run:\n   ```bash fixture-smoke\n   mpi doctor\n   ```\n",
            "> ```bash fixture-smoke\n> mpi doctor\n> ```\n",
            "```{.bash}\nmpi doctor\n```\n",
            "```{ .bash }\nmpi doctor\n```\n",
            "```{#operator .numberLines .bash}\nmpi doctor\n```\n",
            "```{.numberLines.zsh#operator}\nmpi doctor\n```\n",
            "```{ #operator key=value .shell .numberLines }\nmpi doctor\n```\n",
            "```{.sh #operator}\nmpi doctor\n```\n",
        )
        for text in unsupported_blocks:
            with self.subTest(text=text), self.assertRaisesRegex(
                DOCS_SMOKE.DocsContractError,
                "unsupported|Use `bash`",
            ):
                DOCS_SMOKE.parse_command_blocks(Path("docs/example.md"), text)

    def test_failure_output_redacts_credential_assignments(self) -> None:
        output = DOCS_SMOKE._redact(
            'MAILPLUS_TOKEN="synthetic multiword value" '
            '"password": "visible-value" api_key=third-value '
            "Authorization: Bearer fourth-value MAILPLUS_USER=private@example.test"
        )

        self.assertNotIn("synthetic-value", output)
        self.assertNotIn("visible-value", output)
        self.assertNotIn("third-value", output)
        self.assertNotIn("fourth-value", output)
        self.assertNotIn("private@example.test", output)
        self.assertEqual(output.count("<redacted>"), 5)

    def test_failure_output_redacts_sensitive_lines_and_credential_urls(self) -> None:
        output = DOCS_SMOKE._redact(
            "connection failed because password is hunter2\n"
            "connection failed because password was prior-value\n"
            "connection failed with password supplied-value\n"
            "Set-Cookie: session=visible-cookie; Secure\n"
            "Set-Cookie = session=alternate-cookie; Secure\n"
            "set_cookie was session=third-cookie\n"
            "GET https://private-user:private-pass@example.test/mail\n"
            "GET https://example.test/mail?access_token=visible-token&mode=full\n"
            "safe diagnostic remains visible\n"
        )

        self.assertEqual(output.count("<redacted sensitive line>"), 8)
        for secret in (
            "hunter2",
            "prior-value",
            "supplied-value",
            "visible-cookie",
            "alternate-cookie",
            "third-cookie",
            "private-user",
            "private-pass",
            "visible-token",
        ):
            self.assertNotIn(secret, output)
        self.assertIn("safe diagnostic remains visible", output)

    def test_exit_in_one_block_cannot_skip_a_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "operator.md"
            document.write_text(
                "```bash fixture-smoke\nexit 0\n```\n\n"
                "```bash fixture-smoke\nfalse\n```\n",
                encoding="utf-8",
            )
            original_docs = DOCS_SMOKE.OPERATOR_DOCS
            DOCS_SMOKE.OPERATOR_DOCS = (Path("operator.md"),)
            try:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = DOCS_SMOKE.run_fixture_smoke(root)
            finally:
                DOCS_SMOKE.OPERATOR_DOCS = original_docs

        self.assertNotEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
