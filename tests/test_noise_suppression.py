from __future__ import annotations

import json
import unittest
from pathlib import Path

from mailplus_intelligence import SUPPRESSION_FAMILIES, classify_noise_suppression


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "noise_suppression" / "messages.json"
)


def load_noise_suppression_messages() -> tuple[dict[str, object], ...]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return tuple(payload["messages"])


class NoiseSuppressionPolicyTests(unittest.TestCase):
    def test_fixture_corpus_covers_each_suppression_family(self) -> None:
        messages = load_noise_suppression_messages()
        covered_suppressed_families = {
            message["family"]
            for message in messages
            if message["expected_action"] == "suppress"
        }

        self.assertEqual(covered_suppressed_families, SUPPRESSION_FAMILIES)

    def test_suppressed_messages_remain_searchable_but_skip_extraction(self) -> None:
        for message in load_noise_suppression_messages():
            if message["expected_action"] != "suppress":
                continue

            decision = classify_noise_suppression(message)

            self.assertEqual(decision.action, "suppress", message["fixture_id"])
            self.assertEqual(decision.family, message["family"])
            self.assertTrue(decision.searchable_metadata)
            self.assertFalse(decision.extraction_default)
            self.assertIn("locator", message)

    def test_false_positive_fixtures_are_not_silently_suppressed(self) -> None:
        for message in load_noise_suppression_messages():
            if message["expected_action"] == "suppress":
                continue

            decision = classify_noise_suppression(message)

            self.assertEqual(decision.action, message["expected_action"], message["fixture_id"])
            self.assertTrue(decision.searchable_metadata)
            self.assertFalse(
                decision.action == "suppress",
                f"{message['fixture_id']} should not be suppressed by default",
            )


if __name__ == "__main__":
    unittest.main()
