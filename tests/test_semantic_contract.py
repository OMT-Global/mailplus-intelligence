from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from mailplus_intelligence.semantic_contract import (
    SemanticArtifact,
    SemanticArtifactValidationError,
    validate_semantic_artifact,
)


VALID_ARTIFACT = {
    "artifact_id": "artifact-001",
    "artifact_type": "obligation",
    "source_thread_key": "thread-a",
    "source_message_ids": ["<message-001@example.test>"],
    "source_locators": ["fixture-export-001"],
    "evidence_refs": ["subject"],
    "summary": "Operator owes a follow-up.",
    "confidence": "medium",
    "review_status": "review_needed",
    "provenance": "deterministic",
    "extractor_version": "metadata-extractor-v1",
    "model_version": None,
    "rule_version": "metadata-rules-v1",
    "created_at": "2026-01-05T14:05:00Z",
}


class SemanticContractTests(unittest.TestCase):
    def test_golden_outputs_satisfy_contract(self) -> None:
        payload = json.loads(Path("fixtures/semantic/golden_outputs.json").read_text())

        for artifact in payload["artifacts"]:
            with self.subTest(artifact=artifact["artifact_id"]):
                self.assertEqual(validate_semantic_artifact(artifact), [])

    def test_canonical_envelope_is_frozen_and_round_trips_every_field(self) -> None:
        artifact = SemanticArtifact.from_value(VALID_ARTIFACT)

        self.assertEqual(artifact.to_dict(), VALID_ARTIFACT)
        with self.assertRaises(FrozenInstanceError):
            artifact.summary = "mutated"  # type: ignore[misc]
        nested = SemanticArtifact.from_value({
            **VALID_ARTIFACT,
            "source_locators": [
                {"locator_export_id": "fixture-export-001", "locator_uid": "1001"}
            ],
        })
        with self.assertRaises(TypeError):
            nested.source_locators[0]["locator_uid"] = "changed"

    def test_unknown_fields_are_rejected_instead_of_silently_dropped(self) -> None:
        artifact = {**VALID_ARTIFACT, "future_payload": {"body": "not canonical"}}

        self.assertIn(
            "unexpected fields: future_payload",
            validate_semantic_artifact(artifact),
        )
        with self.assertRaises(SemanticArtifactValidationError):
            SemanticArtifact.from_value(artifact)

    def test_invalid_output_reports_useful_errors(self) -> None:
        errors = validate_semantic_artifact({"artifact_id": "bad", "artifact_type": "unknown"})

        self.assertIn("invalid artifact_type", errors)
        self.assertTrue(any(error.startswith("missing fields:") for error in errors))
        self.assertIn("source_locators required", errors)
        self.assertIn("invalid confidence", errors)
        self.assertIn("invalid provenance", errors)

    def test_llm_provenance_requires_model_version(self) -> None:
        artifact = {
            **VALID_ARTIFACT,
            "provenance": "llm",
            "model_version": None,
            "rule_version": None,
        }

        self.assertIn(
            "model_version required for llm provenance",
            validate_semantic_artifact(artifact),
        )
        artifact["model_version"] = "claude-test"
        self.assertEqual(validate_semantic_artifact(artifact), [])

    def test_deterministic_provenance_requires_rule_version(self) -> None:
        artifact = {**VALID_ARTIFACT, "rule_version": None}

        with self.assertRaises(SemanticArtifactValidationError):
            SemanticArtifact.from_value(artifact)

    def test_non_initial_review_state_is_rejected_at_extraction_boundary(self) -> None:
        artifact = {**VALID_ARTIFACT, "review_status": "approved"}

        self.assertIn("invalid review_status", validate_semantic_artifact(artifact))

    def test_artifact_id_cannot_escape_export_directory(self) -> None:
        artifact = {**VALID_ARTIFACT, "artifact_id": "../../outside"}

        self.assertIn("invalid artifact_id", validate_semantic_artifact(artifact))

    def test_locator_rejects_embedded_raw_body_fields(self) -> None:
        artifact = {
            **VALID_ARTIFACT,
            "source_locators": [
                {"locator_export_id": "fixture-export-001", "raw_body": "not allowed"}
            ],
        }

        self.assertIn("source_locators required", validate_semantic_artifact(artifact))

    def test_locator_rejects_embedded_secret_fields(self) -> None:
        artifact = {
            **VALID_ARTIFACT,
            "source_locators": [
                {"locator_export_id": "fixture-export-001", "auth_token": "secret"}
            ],
        }

        self.assertIn("source_locators required", validate_semantic_artifact(artifact))

    def test_locator_rejects_raw_secret_shaped_and_non_json_values(self) -> None:
        secret_shape = "sk-" + "live-not-for-storage"
        for locator in (
            "raw body text with spaces",
            secret_shape,
            {"locator_export_id": "fixture-export-001", "note": "not canonical"},
            {"locator_export_id": "fixture-export-001", "locator_uid": float("nan")},
            {"locator_export_id": "fixture-export-001", 7: "mixed-key"},
        ):
            with self.subTest(locator=locator):
                artifact = {**VALID_ARTIFACT, "source_locators": [locator]}
                self.assertIn(
                    "source_locators required",
                    validate_semantic_artifact(artifact),
                )

    def test_evidence_references_reject_body_dumps_and_secret_shapes(self) -> None:
        secret_shape = "authorization" + ": bearer not-for-storage"
        for reference in ("first line\nsecond line", secret_shape):
            with self.subTest(reference=reference):
                artifact = {**VALID_ARTIFACT, "evidence_refs": [reference]}
                self.assertIn("invalid evidence_ref", validate_semantic_artifact(artifact))

    def test_source_thread_and_locator_labels_reject_raw_or_credential_text(self) -> None:
        sensitive_thread = "authorization" + ":bearer-leaked-source"
        artifact = {**VALID_ARTIFACT, "source_thread_key": sensitive_thread}
        self.assertIn("invalid source_thread_key", validate_semantic_artifact(artifact))

        artifact = {
            **VALID_ARTIFACT,
            "source_locators": [
                {
                    "locator_export_id": "fixture-export-001",
                    "mailbox": "From Alice: this is copied raw mail text",
                }
            ],
        }
        self.assertIn("source_locators required", validate_semantic_artifact(artifact))

    def test_structured_locator_accepts_bounded_mailbox_labels(self) -> None:
        artifact = {
            **VALID_ARTIFACT,
            "source_locators": [
                {
                    "locator_export_id": "fixture-export-001",
                    "locator_uid": 1001,
                    "mailbox": "Archive/Project Atlas",
                }
            ],
        }

        self.assertEqual(validate_semantic_artifact(artifact), [])

    def test_evidence_references_are_bounded(self) -> None:
        artifact = {**VALID_ARTIFACT, "evidence_refs": ["x" * 513]}

        self.assertIn(
            "evidence_ref exceeds maximum length",
            validate_semantic_artifact(artifact),
        )


if __name__ == "__main__":
    unittest.main()
