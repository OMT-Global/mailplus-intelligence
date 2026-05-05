from __future__ import annotations

import json
import unittest
from pathlib import Path

from mailplus_intelligence.classifier import classify_metadata


class BaselineClassifierTests(unittest.TestCase):
    def test_classifier_matches_synthetic_fixture_lanes(self) -> None:
        payload = json.loads(Path("fixtures/classification/cases.json").read_text())

        for case in payload["cases"]:
            with self.subTest(case=case["id"]):
                result = classify_metadata(case["subject"], case["from"])
                self.assertEqual(result.lane, case["lane"])
                self.assertEqual(result.extraction_allowed, case["extraction_allowed"])
                self.assertNotEqual(result.reason_code, "")

    def test_ambiguous_mail_requires_review(self) -> None:
        result = classify_metadata("Quick question", "unknown@example.test")

        self.assertEqual(result.lane, "review_needed")
        self.assertEqual(result.confidence, "low")
        self.assertFalse(result.extraction_allowed)


if __name__ == "__main__":
    unittest.main()
