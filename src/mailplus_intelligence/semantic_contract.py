"""Validation for semantic extraction contract fixtures."""

from __future__ import annotations

REQUIRED_FIELDS = {
    "artifact_id",
    "artifact_type",
    "source_thread_key",
    "source_message_ids",
    "source_locators",
    "evidence_refs",
    "summary",
    "confidence",
    "review_status",
}

ALLOWED_TYPES = {
    "thread_summary",
    "entity_update",
    "obligation",
    "decision",
    "event",
}

ALLOWED_REVIEW_STATUS = {"candidate", "review_needed", "approved", "rejected", "deferred"}


def validate_semantic_artifact(artifact: dict[str, object]) -> list[str]:
    """Return semantic contract validation errors."""

    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(artifact))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")

    if artifact.get("artifact_type") not in ALLOWED_TYPES:
        errors.append("invalid artifact_type")
    if artifact.get("review_status") not in ALLOWED_REVIEW_STATUS:
        errors.append("invalid review_status")
    if not artifact.get("source_locators"):
        errors.append("source_locators required")
    if not artifact.get("evidence_refs"):
        errors.append("evidence_refs required")

    return errors
