"""Tests for the evaluation/regression harness (issue #38)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate import (
    FixtureCorpusError,
    evaluate_classification,
    evaluate_semantic_contract,
    run_evaluation,
)


class EvaluationHarnessTests(unittest.TestCase):
    def test_run_evaluation_passes_all_expected_corpora(self):
        report = run_evaluation(Path("fixtures"))
        self.assertTrue(report["overall_passed"])
        self.assertEqual(report["classification"]["summary"]["total"], 40)
        self.assertEqual(report["semantic_contract"]["summary"]["total"], 2)
        self.assertEqual(report["noise_suppression"]["summary"]["total"], 12)

        classification_ids = [case["case_id"] for case in report["classification"]["cases"]]
        self.assertEqual(len(classification_ids), len(set(classification_ids)))
        self.assertNotIn("?", classification_ids)

    def test_evaluation_report_has_summaries(self):
        report = run_evaluation(Path("fixtures"))
        for section in ("classification", "semantic_contract", "noise_suppression"):
            self.assertIn("summary", report[section])
            self.assertIn("total", report[section]["summary"])
            self.assertIn("passed", report[section]["summary"])
        self.assertEqual(
            report["classification"]["summary"]["by_lane"]["ignore_noise"]["total"],
            10,
        )
        self.assertEqual(report["classification"]["summary"]["false_promotions"], 0)
        self.assertEqual(report["classification"]["summary"]["false_suppressions"], 0)
        self.assertEqual(report["noise_suppression"]["summary"]["false_promotions"], 0)
        self.assertEqual(report["noise_suppression"]["summary"]["false_suppressions"], 0)

    def test_missing_required_corpus_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copytree("fixtures/semantic", Path(tmpdir) / "semantic")
            shutil.copytree("fixtures/noise_suppression", Path(tmpdir) / "noise_suppression")
            with self.assertRaisesRegex(FixtureCorpusError, "classification.*missing"):
                run_evaluation(Path(tmpdir))

    def test_empty_required_corpus_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copytree("fixtures", tmpdir, dirs_exist_ok=True)
            cases_path = Path(tmpdir) / "classification" / "cases.json"
            payload = json.loads(cases_path.read_text(encoding="utf-8"))
            payload["cases"] = []
            cases_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(FixtureCorpusError, "missing or empty"):
                run_evaluation(Path(tmpdir))

    def test_wrong_fixture_expectation_fails_evaluation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copytree("fixtures", tmpdir, dirs_exist_ok=True)
            cases_path = Path(tmpdir) / "classification" / "cases.json"
            payload = json.loads(cases_path.read_text(encoding="utf-8"))
            payload["cases"][0]["lane"] = "ignore_noise"
            cases_path.write_text(json.dumps(payload), encoding="utf-8")

            report = run_evaluation(Path(tmpdir))
            self.assertFalse(report["overall_passed"])
            self.assertEqual(report["classification"]["summary"]["failed"], 1)
            self.assertEqual(report["classification"]["summary"]["false_promotions"], 1)

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
            "provenance": "deterministic",
            "extractor_version": "metadata-extractor-v1",
            "model_version": None,
            "rule_version": "metadata-rules-v1",
            "created_at": "2026-01-10T10:00:00Z",
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
