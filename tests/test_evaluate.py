"""Tests for the evaluation/regression harness (issue #38)."""

from __future__ import annotations

import unittest

from scripts.evaluate import run_evaluation, evaluate_classification, evaluate_semantic_contract
from pathlib import Path


class EvaluationHarnessTests(unittest.TestCase):
    def test_run_evaluation_returns_report(self):
        report = run_evaluation(Path("fixtures"))
        self.assertIn("overall_passed", report)
        self.assertIn("classification", report)
        self.assertIn("semantic_contract", report)
        self.assertIn("noise_suppression", report)

    def test_evaluation_report_has_summaries(self):
        report = run_evaluation(Path("fixtures"))
        for section in ("classification", "semantic_contract", "noise_suppression"):
            self.assertIn("summary", report[section])
            self.assertIn("total", report[section]["summary"])
            self.assertIn("passed", report[section]["summary"])

    def test_evaluate_classification_handles_empty(self):
        results = evaluate_classification([])
        self.assertEqual(results, [])

    def test_evaluate_semantic_contract_handles_valid_artifact(self):
        artifact = {
            "artifact_id": "test-001",
            "artifact_type": "obligation",
            "source_thread_key": "thread-a",
            "source_message_ids": ["<msg@test>"],
            "source_locators": ["fixture-export-001"],
            "evidence_refs": ["fixture-export-001"],
            "summary": "Test summary",
            "confidence": "high",
            "review_status": "candidate",
        }
        results = evaluate_semantic_contract([artifact])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["passed"])

    def test_evaluate_semantic_contract_catches_invalid(self):
        artifact = {"artifact_id": "bad", "artifact_type": "bad_type"}
        results = evaluate_semantic_contract([artifact])
        self.assertFalse(results[0]["passed"])
        self.assertTrue(len(results[0]["errors"]) > 0)


if __name__ == "__main__":
    unittest.main()
