"""LLM-backed semantic extraction using the Anthropic SDK (#70).

Routes classified high-value threads through Claude for richer artifact
extraction.  Designed for offline CI via a fixture-cassette playback dict.
Caches the shared system prompt and thread context using prompt caching.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from .classifier import ClassificationResult
from .extractor import EXTRACTION_LANES, ExtractionCandidate, _locators, _message_ids
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


class LLMNotAvailable(RuntimeError):
    """Raised when LLM extraction is requested but cannot run locally."""


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
) -> str:
    lines = [
        f"Thread ID: {thread.thread_id}",
        f"Lane: {classification.lane}",
        f"Thread confidence: {thread.confidence}",
        f"Message count: {len(thread_messages)}",
    ]
    for msg in thread_messages[:10]:
        lines.append(
            f"  - [{msg.get('date', '?')}] From: {msg.get('from', '?')} | "
            f"Subject: {msg.get('subject', '(no subject)')} | "
            f"Folder: {msg.get('folder', '?')}"
        )
    return "\n".join(lines)


def _parse_llm_response(
    raw: str,
    thread: ReconstructedThread,
    thread_messages: list[dict[str, Any]],
    classification: ClassificationResult,
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
) -> LLMExtractionResult:
    """Run LLM-backed extraction for one thread.

    Pass a ``cassette`` dict mapping thread_id → raw JSON string to play back
    recorded responses in offline / CI environments without hitting the API.
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
    thread_context = _build_thread_context(thread, thread_messages, classification)

    # Cassette playback for offline CI.
    if cassette is not None and thread.thread_id in cassette:
        raw = cassette[thread.thread_id]
        candidates = _parse_llm_response(raw, thread, thread_messages, classification)
        return LLMExtractionResult(candidates=candidates, usage=stats, cassette_hit=True)

    if client is None:
        client = _build_anthropic_client()

    response = client.messages.create(
        model=resolve_llm_model(model),
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

    candidates = _parse_llm_response(raw, thread, thread_messages, classification)
    return LLMExtractionResult(candidates=candidates, usage=stats)


def extract_corpus_with_llm(
    threads: tuple[ReconstructedThread, ...],
    messages: list[dict[str, Any]],
    *,
    client: Any = None,
    model: str | None = None,
    cassette: dict[str, str] | None = None,
) -> LLMExtractionResult:
    """Run LLM extraction over all threads, sharing usage stats."""
    stats = LLMUsageStats()
    all_candidates: list[ExtractionCandidate] = []
    any_cassette_hit = False

    for thread in threads:
        result = extract_with_llm(
            thread, list(messages),
            client=client, model=model, cassette=cassette, usage_stats=stats,
        )
        all_candidates.extend(result.candidates)
        if result.cassette_hit:
            any_cassette_hit = True

    return LLMExtractionResult(
        candidates=all_candidates,
        usage=stats,
        cassette_hit=any_cassette_hit,
    )
