from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(r"^\s*(?:-\s+)?uses: [\w./-]+@[0-9a-f]{40}\s+# v[\w.]+\s*$", re.MULTILINE)


def without_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


class WorkflowPolicyTests(unittest.TestCase):
    def test_every_external_action_is_immutable_and_version_annotated(self) -> None:
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for line in workflow.read_text(encoding="utf-8").splitlines():
                if "uses:" in line:
                    self.assertRegex(line, PINNED_ACTION, f"mutable action reference in {workflow}: {line}")

    def test_pull_request_jobs_are_hosted_and_credential_free(self) -> None:
        workflow = (WORKFLOWS / "pr-fast-ci.yml").read_text(encoding="utf-8")
        executable = without_comments(workflow)
        self.assertIn("pull_request:", executable)
        self.assertNotIn("self-hosted", executable)
        self.assertNotIn("container:", executable)
        self.assertNotIn("docker:", executable)
        self.assertNotRegex(executable, r"runs-on:\s*\$\{\{")
        self.assertEqual(executable.count("uses: actions/checkout@"), executable.count("persist-credentials: false"))
        self.assertIn("name: Actionlint", executable)
        self.assertIn("name: Dependency Review", executable)
        self.assertIn("name: CI Gate", executable)

    def test_claude_automation_is_hosted_and_actor_gated(self) -> None:
        workflow = without_comments((WORKFLOWS / "claude.yml").read_text(encoding="utf-8"))
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("github.actor == 'jmcte'", workflow)
        self.assertIn("persist-credentials: false", workflow)


if __name__ == "__main__":
    unittest.main()
