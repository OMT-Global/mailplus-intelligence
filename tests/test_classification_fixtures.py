from __future__ import annotations

import json
import unittest
from pathlib import Path


class ClassificationFixtureTests(unittest.TestCase):
    def test_fixture_corpus_covers_required_lanes_and_noise_count(self) -> None:
        payload = json.loads(Path("fixtures/classification/cases.json").read_text())
        cases = payload["cases"]

        lanes = {}
        for case in cases:
            lanes.setdefault(case["lane"], []).append(case)

        for lane in ("vip", "project", "admin", "financial", "travel", "legal"):
            self.assertGreaterEqual(len(lanes.get(lane, [])), 5)
            self.assertTrue(all(case["extraction_allowed"] for case in lanes[lane]))

        self.assertGreaterEqual(len(lanes.get("ignore_noise", [])), 10)
        self.assertTrue(all(not case["extraction_allowed"] for case in lanes["ignore_noise"]))

    def test_fixture_corpus_is_synthetic_and_body_free(self) -> None:
        payload = json.loads(Path("fixtures/classification/cases.json").read_text())

        self.assertEqual(payload["privacy"]["source"], "synthetic")
        self.assertFalse(payload["privacy"]["raw_body_included"])
        for case in payload["cases"]:
            self.assertNotIn("body", case)
            self.assertNotIn("raw_body", case)


if __name__ == "__main__":
    unittest.main()
