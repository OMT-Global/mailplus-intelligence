from __future__ import annotations

import json
import unittest
from pathlib import Path

from mailplus_intelligence.semantic_contract import validate_semantic_artifact


class SemanticContractTests(unittest.TestCase):
    def test_golden_outputs_satisfy_contract(self) -> None:
        payload = json.loads(Path("fixtures/semantic/golden_outputs.json").read_text())

        for artifact in payload["artifacts"]:
            with self.subTest(artifact=artifact["artifact_id"]):
                self.assertEqual(validate_semantic_artifact(artifact), [])

    def test_invalid_output_reports_useful_errors(self) -> None:
        errors = validate_semantic_artifact({"artifact_id": "bad", "artifact_type": "unknown"})

        self.assertIn("invalid artifact_type", errors)
        self.assertTrue(any(error.startswith("missing fields:") for error in errors))
        self.assertIn("source_locators required", errors)


if __name__ == "__main__":
    unittest.main()
