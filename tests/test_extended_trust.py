import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("extended_trust", ROOT / "scripts/ci/check-extended-trust.py")
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)

class ExtendedTrustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".github/workflows").mkdir(parents=True)
        for name in ("extended-trusted.yml", "extended-validation.yml"):
            target = self.root / ".github/workflows" / name
            target.write_bytes((ROOT / ".github/workflows" / name).read_bytes())

    def test_pristine(self):
        GUARD.validate(self.root)

    def test_mutations(self):
        target = self.root / ".github/workflows/extended-trusted.yml"
        original = target.read_text()
        mutations = [
            ("github.event_name == 'schedule'", "github.event_name == 'pull_request'"),
            ("github.repository == 'OMT-Global/mailplus-intelligence'", "true"),
            ("group: linux-flow-trusted", "group: linux-public"),
            ("persist-credentials: false", "persist-credentials: true"),
            ("bash scripts/ci/run-extended-validation.sh", "echo skipped"),
            ("workflow_call:", "workflow_call:\n    inputs: {}"),
        ]
        for before, after in mutations:
            with self.subTest(before=before):
                self.assertIn(before, original)
                target.write_text(original.replace(before, after))
                with self.assertRaises(ValueError):
                    GUARD.validate(self.root)
        target.write_text(original)
        GUARD.validate(self.root)

    def test_mutable_caller_and_overrides(self):
        target = self.root / ".github/workflows/extended-validation.yml"
        original = target.read_text()
        for changed in (original.replace(GUARD.PIN, "main"), original + "    secrets: inherit\n", original + "    runs-on: self-hosted\n"):
            target.write_text(changed)
            with self.assertRaises(ValueError):
                GUARD.validate(self.root)
