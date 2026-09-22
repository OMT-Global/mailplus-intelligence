"""Canonical semantic artifact envelope and validation."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any


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
    "provenance",
    "extractor_version",
    "model_version",
    "rule_version",
    "created_at",
}

ALLOWED_TYPES = {
    "thread_summary",
    "entity_update",
    "obligation",
    "decision",
    "event",
}

ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_INITIAL_REVIEW_STATUS = {"candidate", "review_needed"}
ALLOWED_PROVENANCE = {"deterministic", "llm"}
MAX_SUMMARY_CHARS = 16_384
MAX_EVIDENCE_REFS = 100
MAX_EVIDENCE_REF_CHARS = 256
MAX_SOURCE_MESSAGE_IDS = 100
MAX_SOURCE_MESSAGE_ID_CHARS = 1_024
MAX_SOURCE_LOCATORS = 100
MAX_LOCATOR_JSON_CHARS = 4_096
MAX_SOURCE_THREAD_KEY_CHARS = 1_024

_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPAQUE_LOCATOR = re.compile(r"^[A-Za-z0-9<][A-Za-z0-9._:@/+%<>-]{0,511}$")
_MAILBOX_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@/+%<>&()\[\]-]{0,254}$")
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:sk-(?:live|proj)-|ghp" + r"_|github_pat" + r"_|bearer\s+|"
    r"\b(?:api[_-]?key|authorization|cookie|password|secret|session|token)\s*[:=])"
)
_ALLOWED_LOCATOR_KEYS = {
    "account",
    "account_id",
    "export_id",
    "folder",
    "locator_export_id",
    "locator_uid",
    "mailbox",
    "provider",
    "source",
    "uid",
    "uidvalidity",
}
_PROHIBITED_LOCATOR_KEYS = {
    "api_key",
    "attachment_data",
    "attachment_payload",
    "auth_token",
    "authorization",
    "body",
    "body_html",
    "body_text",
    "cookie",
    "credentials",
    "html_body",
    "password",
    "prompt_payload",
    "raw_body",
    "raw_content",
    "secret",
    "session",
    "text_body",
    "token",
}


class SemanticArtifactValidationError(ValueError):
    """Raised when an artifact does not satisfy the canonical envelope."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__("invalid semantic artifact: " + "; ".join(self.errors))


@dataclass(frozen=True)
class SemanticArtifact:
    """Immutable extraction output persisted by the promotion queue.

    Review decisions are deliberately not part of this value. ``review_status``
    is the extraction-time state and remains immutable after enqueue.
    """

    artifact_id: str
    artifact_type: str
    source_thread_key: str
    source_message_ids: tuple[str, ...]
    source_locators: tuple[Any, ...]
    evidence_refs: tuple[str, ...]
    summary: str
    confidence: str
    review_status: str
    provenance: str
    extractor_version: str
    model_version: str | None
    rule_version: str | None
    created_at: str

    @classmethod
    def from_value(
        cls,
        value: Mapping[str, Any] | object,
        *,
        artifact_id: str | None = None,
        created_at: str | None = None,
    ) -> "SemanticArtifact":
        """Build and validate an envelope without changing supplied values."""

        payload = _as_mapping(value)
        payload.setdefault("artifact_id", artifact_id or str(uuid.uuid4()))
        payload.setdefault("created_at", created_at or _utc_now())

        errors = validate_semantic_artifact(payload)
        if errors:
            raise SemanticArtifactValidationError(errors)

        return cls(
            artifact_id=payload["artifact_id"],
            artifact_type=payload["artifact_type"],
            source_thread_key=payload["source_thread_key"],
            source_message_ids=tuple(payload["source_message_ids"]),
            source_locators=tuple(_freeze_json(locator) for locator in payload["source_locators"]),
            evidence_refs=tuple(payload["evidence_refs"]),
            summary=payload["summary"],
            confidence=payload["confidence"],
            review_status=payload["review_status"],
            provenance=payload["provenance"],
            extractor_version=payload["extractor_version"],
            model_version=payload["model_version"],
            rule_version=payload["rule_version"],
            created_at=payload["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready copy of every canonical field."""

        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "source_thread_key": self.source_thread_key,
            "source_message_ids": list(self.source_message_ids),
            "source_locators": [_thaw_json(locator) for locator in self.source_locators],
            "evidence_refs": list(self.evidence_refs),
            "summary": self.summary,
            "confidence": self.confidence,
            "review_status": self.review_status,
            "provenance": self.provenance,
            "extractor_version": self.extractor_version,
            "model_version": self.model_version,
            "rule_version": self.rule_version,
            "created_at": self.created_at,
        }


def validate_semantic_artifact(artifact: Mapping[str, Any] | object) -> list[str]:
    """Return canonical semantic envelope validation errors."""

    value = _as_mapping(artifact)
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(value))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    unexpected = sorted(str(key)[:80] for key in set(value) - REQUIRED_FIELDS)
    if unexpected:
        errors.append(f"unexpected fields: {', '.join(unexpected)}")

    if not _nonempty_string(value.get("artifact_id")):
        errors.append("artifact_id required")
    elif not _ARTIFACT_ID.fullmatch(value["artifact_id"]):
        errors.append("invalid artifact_id")
    if value.get("artifact_type") not in ALLOWED_TYPES:
        errors.append("invalid artifact_type")
    if not _nonempty_string(value.get("source_thread_key")):
        errors.append("source_thread_key required")
    elif len(value["source_thread_key"]) > MAX_SOURCE_THREAD_KEY_CHARS:
        errors.append("source_thread_key exceeds maximum length")
    elif not _safe_opaque_reference(value["source_thread_key"]):
        errors.append("invalid source_thread_key")
    if not _string_sequence(value.get("source_message_ids"), require_values=True):
        errors.append("source_message_ids required")
    elif len(value["source_message_ids"]) > MAX_SOURCE_MESSAGE_IDS:
        errors.append("too many source_message_ids")
    elif any(len(message_id) > MAX_SOURCE_MESSAGE_ID_CHARS for message_id in value["source_message_ids"]):
        errors.append("source_message_id exceeds maximum length")
    elif any(not _safe_opaque_reference(message_id) for message_id in value["source_message_ids"]):
        errors.append("invalid source_message_id")
    if not _valid_locators(value.get("source_locators")):
        errors.append("source_locators required")
    if not _string_sequence(value.get("evidence_refs"), require_values=True):
        errors.append("evidence_refs required")
    else:
        if len(value["evidence_refs"]) > MAX_EVIDENCE_REFS:
            errors.append("too many evidence_refs")
        if any(len(reference) > MAX_EVIDENCE_REF_CHARS for reference in value["evidence_refs"]):
            errors.append("evidence_ref exceeds maximum length")
        if any(not _safe_evidence_reference(reference) for reference in value["evidence_refs"]):
            errors.append("invalid evidence_ref")
    if not _nonempty_string(value.get("summary")):
        errors.append("summary required")
    elif len(value["summary"]) > MAX_SUMMARY_CHARS:
        errors.append("summary exceeds maximum length")
    if value.get("confidence") not in ALLOWED_CONFIDENCE:
        errors.append("invalid confidence")
    if value.get("review_status") not in ALLOWED_INITIAL_REVIEW_STATUS:
        errors.append("invalid review_status")

    provenance = value.get("provenance")
    if provenance not in ALLOWED_PROVENANCE:
        errors.append("invalid provenance")
    if not _nonempty_string(value.get("extractor_version")):
        errors.append("extractor_version required")
    if provenance == "deterministic" and not _nonempty_string(value.get("rule_version")):
        errors.append("rule_version required for deterministic provenance")
    if provenance == "llm" and not _nonempty_string(value.get("model_version")):
        errors.append("model_version required for llm provenance")
    if value.get("model_version") is not None and not _nonempty_string(value.get("model_version")):
        errors.append("invalid model_version")
    if value.get("rule_version") is not None and not _nonempty_string(value.get("rule_version")):
        errors.append("invalid rule_version")
    if not _timezone_aware_timestamp(value.get("created_at")):
        errors.append("created_at must be a timezone-aware ISO-8601 timestamp")

    return errors


def _as_mapping(value: Mapping[str, Any] | object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, SemanticArtifact):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError("semantic artifact must be a mapping or dataclass")


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _string_sequence(value: object, *, require_values: bool) -> bool:
    if not _is_sequence(value):
        return False
    values = list(value)
    if require_values and not values:
        return False
    return all(_nonempty_string(item) for item in values)


def _valid_locators(value: object) -> bool:
    if not _is_sequence(value) or not value or len(value) > MAX_SOURCE_LOCATORS:
        return False
    for locator in value:
        if _nonempty_string(locator):
            if len(locator) > MAX_LOCATOR_JSON_CHARS or not _safe_opaque_reference(locator):
                return False
            continue
        if not isinstance(locator, Mapping):
            return False
        export_id = locator.get("locator_export_id") or locator.get("export_id")
        if not _nonempty_string(export_id) or not _safe_opaque_reference(export_id):
            return False
        if any(not isinstance(key, str) or key not in _ALLOWED_LOCATOR_KEYS for key in locator):
            return False
        if any(not _safe_locator_value(key, item) for key, item in locator.items()):
            return False
        try:
            encoded = json.dumps(locator, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError):
            return False
        if len(encoded) > MAX_LOCATOR_JSON_CHARS or _contains_prohibited_locator_key(locator):
            return False
    return True


def _safe_opaque_reference(value: str) -> bool:
    return bool(_OPAQUE_LOCATOR.fullmatch(value)) and not _SENSITIVE_VALUE.search(value)


def _safe_evidence_reference(value: str) -> bool:
    return (
        "\n" not in value
        and "\r" not in value
        and "\x00" not in value
        and not _SENSITIVE_VALUE.search(value)
    )


def _safe_locator_value(key: str, value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, str):
        if key in {"folder", "mailbox"}:
            return (
                bool(_MAILBOX_LABEL.fullmatch(value))
                and len(value.split()) <= 8
                and not _SENSITIVE_VALUE.search(value)
            )
        return _safe_opaque_reference(value)
    return False


def _contains_prohibited_locator_key(value: Mapping[str, Any]) -> bool:
    for key, item in value.items():
        if str(key).lower().replace("-", "_") in _PROHIBITED_LOCATOR_KEYS:
            return True
        if isinstance(item, Mapping) and _contains_prohibited_locator_key(item):
            return True
        if _is_sequence(item):
            for member in item:
                if isinstance(member, Mapping) and _contains_prohibited_locator_key(member):
                    return True
    return False


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if _is_sequence(value):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if _is_sequence(value):
        return [_thaw_json(item) for item in value]
    return value


def _timezone_aware_timestamp(value: object) -> bool:
    if not _nonempty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
