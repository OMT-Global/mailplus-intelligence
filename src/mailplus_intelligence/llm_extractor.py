"""LLM-backed semantic extraction using the Anthropic SDK (#70).

Routes classified high-value threads through Claude for richer artifact
extraction.  Designed for offline CI via a fixture-cassette playback dict.
Caches the shared system prompt and thread context using prompt caching.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .classifier import ClassificationResult
from .extractor import EXTRACTION_LANES, ExtractionCandidate, _locators, _message_ids
from .sqlite import enforce_owner_only_database_files
from .threading import ReconstructedThread


_SYSTEM_PROMPT = (
    "You are MailPlus Intelligence, a semantic extraction engine for email metadata. "
    "You receive classified thread metadata (no raw body) and produce structured "
    "semantic artifacts conforming to the extraction contract. "
    "Respond with a single JSON array of artifact objects. "
    "Each artifact must have: artifact_type (thread_summary|obligation|event|decision|entity_update), "
    "summary (plain-English string), confidence (high|medium|low), "
    "review_status (candidate|review_needed). "
    "Be concise and grounded only in the metadata provided. "
    "If nothing actionable is present, return a single thread_summary artifact."
)

_EXTRACTION_LANES_LLM = EXTRACTION_LANES
DEFAULT_LLM_MODEL = "claude-opus-4-7"
LLM_EXTRA_INSTALL_HINT = "pip install 'mailplus-intelligence[llm]'"
LLM_EXTRACTOR_VERSION = "llm-extractor-v1"
MIN_PSEUDONYMIZATION_KEY_BYTES = 32


class LLMNotAvailable(RuntimeError):
    """Raised when LLM extraction is requested but cannot run locally."""


class LLMEgressPolicyError(LLMNotAvailable):
    """Raised when a model request is not authorized by provider policy."""


@dataclass(frozen=True)
class LLMProviderPolicy:
    """Explicit provider mode and data classes authorized for model use."""

    mode: str = "disabled"
    provider: str = "none"
    allowed_data_classes: frozenset[str] = field(default_factory=frozenset)
    cloud_opt_in: bool = False
    pseudonymize_cloud_metadata: bool = True
    pseudonymization_key: str | None = None


def load_llm_provider_policy(
    environ: Mapping[str, str] | None = None,
) -> LLMProviderPolicy:
    """Load fail-closed provider policy from process environment."""

    values = os.environ if environ is None else environ
    mode = values.get("MAILPLUS_LLM_PROVIDER_MODE", "disabled").strip().lower()
    provider_default = "anthropic" if mode == "cloud" else mode
    provider = values.get("MAILPLUS_LLM_PROVIDER", provider_default or "none").strip().lower()
    configured_classes = values.get("MAILPLUS_LLM_DATA_CLASSES", "")
    if configured_classes:
        allowed_data_classes = frozenset(
            item.strip() for item in configured_classes.split(",") if item.strip()
        )
    elif mode == "cloud":
        allowed_data_classes = frozenset({"metadata-redacted"})
    elif mode == "local":
        allowed_data_classes = frozenset({"metadata"})
    else:
        allowed_data_classes = frozenset()

    cloud_opt_in = values.get("MAILPLUS_LLM_CLOUD_OPT_IN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return LLMProviderPolicy(
        mode=mode,
        provider=provider,
        allowed_data_classes=allowed_data_classes,
        cloud_opt_in=cloud_opt_in,
        pseudonymization_key=values.get("MAILPLUS_LLM_PSEUDONYMIZATION_KEY") or None,
    )


def resolve_llm_model(model: str | None = None) -> str:
    """Resolve the configured LLM model name."""

    if model:
        return model
    return os.environ.get("MAILPLUS_LLM_MODEL") or DEFAULT_LLM_MODEL


def _build_anthropic_client() -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise LLMNotAvailable(
            f"Anthropic SDK is not installed; run {LLM_EXTRA_INSTALL_HINT} to enable LLM extraction."
        ) from exc

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMNotAvailable(
            "ANTHROPIC_API_KEY is not set; set it or pass a cassette for offline LLM extraction."
        )

    return anthropic.Anthropic()


@dataclass
class LLMUsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0


@dataclass
class LLMExtractionResult:
    candidates: list[ExtractionCandidate]
    usage: LLMUsageStats
    cassette_hit: bool = False


def _build_thread_context(
    thread: ReconstructedThread,
    thread_messages: list[dict[str, Any]],
    classification: ClassificationResult,
    *,
    pseudonymize_metadata: bool = False,
    pseudonymization_key: str | None = None,
) -> str:
    thread_ref = (
        _pseudonymize_metadata("thread", thread.thread_id, pseudonymization_key)
        if pseudonymize_metadata
        else thread.thread_id
    )
    lines = [
        f"Thread ID: {thread_ref}",
        f"Lane: {classification.lane}",
        f"Thread confidence: {thread.confidence}",
        f"Message count: {len(thread_messages)}",
    ]
    for msg in thread_messages[:10]:
        sender = str(msg.get("from", "?"))
        subject = str(msg.get("subject", "(no subject)"))
        folder = str(msg.get("folder", "?"))
        message_date = str(msg.get("date", "?"))
        if pseudonymize_metadata:
            sender = _pseudonymize_metadata("sender", sender, pseudonymization_key)
            subject = _pseudonymize_metadata("subject", subject, pseudonymization_key)
            folder = _pseudonymize_metadata("folder", folder, pseudonymization_key)
            message_date = _pseudonymize_metadata("date", message_date, pseudonymization_key)
        lines.append(
            f"  - [{message_date}] From: {sender} | "
            f"Subject: {subject} | Folder: {folder}"
        )
    return "\n".join(lines)


def _pseudonymize_metadata(kind: str, value: str, key: str | None) -> str:
    if not key:
        raise LLMEgressPolicyError("cloud pseudonymization requires a configured key")
    digest = hmac.new(
        key.encode("utf-8"),
        f"{kind}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{kind}:{digest}"


_AUDIT_LABEL = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_SECRET_SHAPED_AUDIT_LABEL = re.compile(
    r"(?i)(?:^|[-_.:/])(?:api[-_]?key|bearer|password|secret|token|sk-(?:ant|live|test))"
    r"(?:$|[-_.:/])"
)


def _validate_audit_label(label: str, field_name: str) -> None:
    if (
        not isinstance(label, str)
        or not _AUDIT_LABEL.fullmatch(label)
        or _SECRET_SHAPED_AUDIT_LABEL.search(label)
    ):
        raise LLMEgressPolicyError(f"{field_name} is not safe for audit metadata")


def _authorize_model_request(
    policy: LLMProviderPolicy,
    requested_data_classes: frozenset[str],
    model: str,
    audit_connection: sqlite3.Connection | None,
    requested_mode: str,
    requested_provider: str,
) -> None:
    if policy.mode not in {"disabled", "local", "cloud"}:
        raise LLMEgressPolicyError("unsupported LLM provider mode")
    if policy.mode == "disabled":
        raise LLMEgressPolicyError(
            "LLM extraction is disabled; explicitly configure local or cloud provider mode"
        )
    if policy.mode == "cloud" and not policy.cloud_opt_in:
        raise LLMEgressPolicyError(
            "cloud LLM extraction requires MAILPLUS_LLM_CLOUD_OPT_IN=true"
        )
    if policy.mode == "cloud" and not policy.pseudonymize_cloud_metadata:
        raise LLMEgressPolicyError("cloud metadata pseudonymization cannot be disabled")
    if policy.mode == "cloud" and not policy.pseudonymization_key:
        raise LLMEgressPolicyError(
            "cloud LLM extraction requires MAILPLUS_LLM_PSEUDONYMIZATION_KEY"
        )
    if (
        policy.mode == "cloud"
        and len(policy.pseudonymization_key.encode("utf-8"))
        < MIN_PSEUDONYMIZATION_KEY_BYTES
    ):
        raise LLMEgressPolicyError(
            "MAILPLUS_LLM_PSEUDONYMIZATION_KEY must be at least 32 UTF-8 bytes"
        )
    if not requested_data_classes:
        raise LLMEgressPolicyError("at least one model data class must be declared")
    _validate_audit_label(policy.provider, "provider")
    _validate_audit_label(model, "model")
    for data_class in requested_data_classes:
        _validate_audit_label(data_class, "data class")
    if not requested_data_classes.issubset(policy.allowed_data_classes):
        denied = sorted(requested_data_classes - policy.allowed_data_classes)
        raise LLMEgressPolicyError(
            f"model data classes are not authorized by provider policy: {', '.join(denied)}"
        )
    if audit_connection is None:
        raise LLMEgressPolicyError("model requests require a durable audit connection")
    if audit_connection.in_transaction:
        raise LLMEgressPolicyError("model audit connection must not have an active transaction")
    database_rows = audit_connection.execute("PRAGMA database_list").fetchall()
    if not any(row[1] == "main" and row[2] for row in database_rows):
        raise LLMEgressPolicyError("model audit connection must be file-backed")
    if requested_mode != policy.mode or requested_provider != policy.provider:
        raise LLMEgressPolicyError("model client does not match the authorized provider policy")
    if requested_mode == "cloud" and requested_provider != "anthropic":
        raise LLMEgressPolicyError("configured cloud provider has no supported client adapter")


def _record_egress_event(
    connection: sqlite3.Connection,
    request_id: str,
    thread_id: str,
    policy: LLMProviderPolicy,
    model: str,
    data_classes: frozenset[str],
    status: str,
) -> None:
    connection.execute(
        """
        INSERT INTO llm_egress_events (
          request_id, thread_ref_hash, provider_mode, provider, model, data_classes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            hmac.new(
                (policy.pseudonymization_key or "local-audit").encode("utf-8"),
                thread_id.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest(),
            policy.mode,
            policy.provider,
            model,
            json.dumps(sorted(data_classes), separators=(",", ":")),
            status,
        ),
    )
    connection.commit()
    enforce_owner_only_database_files(connection)


def _parse_llm_response(
    raw: str,
    thread: ReconstructedThread,
    thread_messages: list[dict[str, Any]],
    classification: ClassificationResult,
    model_version: str,
) -> list[ExtractionCandidate]:
    locs = _locators(thread_messages)
    msg_ids = _message_ids(thread_messages)

    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            items = [items]
    except (json.JSONDecodeError, ValueError):
        items = [{"artifact_type": "thread_summary", "summary": raw.strip(),
                  "confidence": "low", "review_status": "review_needed"}]

    candidates: list[ExtractionCandidate] = []
    for item in items:
        artifact_type = item.get("artifact_type", "thread_summary")
        summary = item.get("summary", "")
        confidence = item.get("confidence", "medium")
        review_status = item.get("review_status", "candidate")
        candidates.append(
            ExtractionCandidate(
                artifact_id=str(uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"llm:{thread.thread_id}:{artifact_type}:{summary[:40]}",
                )),
                artifact_type=artifact_type,
                source_thread_key=thread.thread_id,
                source_message_ids=msg_ids,
                source_locators=locs,
                evidence_refs=locs,
                summary=summary,
                confidence=confidence,
                review_status=review_status,
                provenance="llm",
                extractor_version=LLM_EXTRACTOR_VERSION,
                model_version=model_version,
                rule_version=None,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return candidates


def extract_with_llm(
    thread: ReconstructedThread,
    messages: list[dict[str, Any]],
    *,
    client: Any = None,
    model: str | None = None,
    cassette: dict[str, str] | None = None,
    usage_stats: LLMUsageStats | None = None,
    provider_policy: LLMProviderPolicy | None = None,
    data_classes: frozenset[str] | None = None,
    audit_connection: sqlite3.Connection | None = None,
    client_mode: str | None = None,
    client_provider: str | None = None,
) -> LLMExtractionResult:
    """Run LLM-backed extraction for one thread.

    Pass a ``cassette`` dict mapping thread_id → raw JSON string to play back
    recorded responses in offline / CI environments without hitting the API.
    Every non-cassette call requires an explicit provider policy, authorized
    data classes, and a durable audit connection.
    """
    thread_messages = [m for m in messages if m["fixture_id"] in thread.message_fixture_ids]
    if not thread_messages:
        return LLMExtractionResult(candidates=[], usage=LLMUsageStats())

    from .classifier import classify_metadata

    representative = thread_messages[0]
    classification = classify_metadata(
        str(representative.get("subject", "")),
        str(representative.get("from", "")),
    )

    if not classification.extraction_allowed or classification.lane not in _EXTRACTION_LANES_LLM:
        return LLMExtractionResult(candidates=[], usage=LLMUsageStats())

    stats = usage_stats or LLMUsageStats()
    resolved_model = resolve_llm_model(model)

    # Cassette playback for offline CI.
    if cassette is not None and thread.thread_id in cassette:
        raw = cassette[thread.thread_id]
        candidates = _parse_llm_response(
            raw,
            thread,
            thread_messages,
            classification,
            resolved_model,
        )
        return LLMExtractionResult(candidates=candidates, usage=stats, cassette_hit=True)

    policy = provider_policy or load_llm_provider_policy()
    resolved_model = resolve_llm_model(model)
    requested_data_classes = (
        frozenset({"metadata-redacted" if policy.mode == "cloud" else "metadata"})
        if data_classes is None
        else data_classes
    )
    if client is None:
        requested_mode = "cloud"
        requested_provider = "anthropic"
    else:
        requested_mode = client_mode or getattr(client, "provider_mode", "")
        requested_provider = client_provider or getattr(client, "provider_name", "")
    _authorize_model_request(
        policy,
        requested_data_classes,
        resolved_model,
        audit_connection,
        requested_mode,
        requested_provider,
    )
    assert audit_connection is not None

    thread_context = _build_thread_context(
        thread,
        thread_messages,
        classification,
        pseudonymize_metadata=policy.mode == "cloud",
        pseudonymization_key=policy.pseudonymization_key,
    )
    request_id = str(uuid.uuid4())
    _record_egress_event(
        audit_connection,
        request_id,
        thread.thread_id,
        policy,
        resolved_model,
        requested_data_classes,
        "authorized",
    )

    try:
        if client is None:
            if policy.mode == "local":
                raise LLMNotAvailable("local provider mode requires an explicit local model client")
            client = _build_anthropic_client()
        response = client.messages.create(
            model=resolved_model,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": thread_context,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        )

        stats.calls += 1
        usage = response.usage
        stats.input_tokens += getattr(usage, "input_tokens", 0)
        stats.output_tokens += getattr(usage, "output_tokens", 0)
        stats.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0)
        stats.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0)

        raw = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                raw = block.text
                break

        candidates = _parse_llm_response(
            raw,
            thread,
            thread_messages,
            classification,
            resolved_model,
        )
        _record_egress_event(
            audit_connection,
            request_id,
            thread.thread_id,
            policy,
            resolved_model,
            requested_data_classes,
            "completed",
        )
    except Exception:
        if audit_connection.in_transaction:
            audit_connection.rollback()
        _record_egress_event(
            audit_connection,
            request_id,
            thread.thread_id,
            policy,
            resolved_model,
            requested_data_classes,
            "failed",
        )
        raise
    return LLMExtractionResult(candidates=candidates, usage=stats)


def extract_corpus_with_llm(
    threads: tuple[ReconstructedThread, ...],
    messages: list[dict[str, Any]],
    *,
    client: Any = None,
    model: str | None = None,
    cassette: dict[str, str] | None = None,
    provider_policy: LLMProviderPolicy | None = None,
    data_classes: frozenset[str] | None = None,
    audit_connection: sqlite3.Connection | None = None,
    client_mode: str | None = None,
    client_provider: str | None = None,
) -> LLMExtractionResult:
    """Run LLM extraction over all threads, sharing usage stats."""
    stats = LLMUsageStats()
    all_candidates: list[ExtractionCandidate] = []
    any_cassette_hit = False

    for thread in threads:
        result = extract_with_llm(
            thread, list(messages),
            client=client, model=model, cassette=cassette, usage_stats=stats,
            provider_policy=provider_policy,
            data_classes=data_classes,
            audit_connection=audit_connection,
            client_mode=client_mode,
            client_provider=client_provider,
        )
        all_candidates.extend(result.candidates)
        if result.cassette_hit:
            any_cassette_hit = True

    return LLMExtractionResult(
        candidates=all_candidates,
        usage=stats,
        cassette_hit=any_cassette_hit,
    )
