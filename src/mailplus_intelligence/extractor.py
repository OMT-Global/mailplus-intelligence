"""Deterministic extraction pipeline for selected high-value mail (#6).

Generates thread summaries, obligation candidates, and entity update candidates
from classified metadata only — no raw body required.
Outputs conform to the semantic artifact contract (semantic_contract.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from .classifier import ClassificationResult, classify_metadata
from .threading import ReconstructedThread


EXTRACTION_LANES = frozenset({
    "vip", "project", "admin", "financial", "travel", "legal",
})

OBLIGATION_SUBJECT_TOKENS = (
    "follow-up",
    "action required",
    "please confirm",
    "please review",
    "deadline",
    "due by",
    "reminder",
    "need your",
    "sign",
    "approve",
    "nda",
    "contract",
    "invoice",
)

EVENT_SUBJECT_TOKENS = (
    "flight",
    "hotel",
    "rental car",
    "itinerary",
    "booking",
    "reservation",
    "confirmation",
    "invoice",
    "payment",
    "statement",
    "billing",
    "filing",
    "settlement",
)


@dataclass(frozen=True)
class ExtractionCandidate:
    """A single deterministic extraction candidate conforming to the semantic contract."""

    artifact_id: str
    artifact_type: str
    source_thread_key: str
    source_message_ids: tuple[str, ...]
    source_locators: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    summary: str
    confidence: str
    review_status: str
    provenance: str


def extract_from_thread(
    thread: ReconstructedThread,
    messages: list[dict[str, Any]],
) -> list[ExtractionCandidate]:
    """Run deterministic extraction for one reconstructed thread.

    Returns a list of candidates (may be empty if the thread is suppressed).
    """
    thread_messages = [
        m for m in messages if m["fixture_id"] in thread.message_fixture_ids
    ]
    if not thread_messages:
        return []

    representative = thread_messages[0]
    classification = classify_metadata(
        str(representative.get("subject", "")),
        str(representative.get("from", "")),
    )

    if not classification.extraction_allowed or classification.lane not in EXTRACTION_LANES:
        return []

    candidates: list[ExtractionCandidate] = []

    summary_candidate = _build_thread_summary(thread, thread_messages, classification)
    candidates.append(summary_candidate)

    obligation = _try_obligation(thread, thread_messages, classification)
    if obligation:
        candidates.append(obligation)

    event = _try_event(thread, thread_messages, classification)
    if event:
        candidates.append(event)

    return candidates


def extract_from_corpus(
    threads: tuple[ReconstructedThread, ...],
    messages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[ExtractionCandidate]:
    """Extract candidates from all threads in a corpus."""
    all_candidates: list[ExtractionCandidate] = []
    msg_list = list(messages)
    for thread in threads:
        all_candidates.extend(extract_from_thread(thread, msg_list))
    return all_candidates


def _locators(thread_messages: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(m["locator"].get("export_id", ""))
        for m in thread_messages
        if m.get("locator", {}).get("export_id")
    )


def _message_ids(thread_messages: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(m["message_id"]) for m in thread_messages if m.get("message_id"))


def _build_thread_summary(
    thread: ReconstructedThread,
    thread_messages: list[dict[str, Any]],
    classification: ClassificationResult,
) -> ExtractionCandidate:
    subjects = list({str(m.get("subject", "")) for m in thread_messages})
    senders = list({str(m.get("from", "")) for m in thread_messages})
    count = len(thread_messages)
    lane = classification.lane
    subject_str = subjects[0] if subjects else "(no subject)"
    sender_str = ", ".join(senders[:3])
    summary = (
        f"{lane.upper()} thread '{subject_str}' — {count} message(s) between {sender_str}. "
        f"Thread confidence: {thread.confidence}."
    )
    locs = _locators(thread_messages)
    return ExtractionCandidate(
        artifact_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"summary:{thread.thread_id}")),
        artifact_type="thread_summary",
        source_thread_key=thread.thread_id,
        source_message_ids=_message_ids(thread_messages),
        source_locators=locs,
        evidence_refs=locs,
        summary=summary,
        confidence="high" if thread.confidence == "high" else "medium",
        review_status="candidate",
        provenance="deterministic",
    )


def _try_obligation(
    thread: ReconstructedThread,
    thread_messages: list[dict[str, Any]],
    classification: ClassificationResult,
) -> ExtractionCandidate | None:
    for msg in thread_messages:
        subject = str(msg.get("subject", "")).lower()
        if any(token in subject for token in OBLIGATION_SUBJECT_TOKENS):
            locs = _locators([msg])
            return ExtractionCandidate(
                artifact_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"obligation:{msg['message_id']}")),
                artifact_type="obligation",
                source_thread_key=thread.thread_id,
                source_message_ids=(str(msg["message_id"]),),
                source_locators=locs,
                evidence_refs=locs,
                summary=f"Possible commitment or action item: '{msg.get('subject', '')}' from {msg.get('from', '?')}.",
                confidence="low",
                review_status="review_needed",
                provenance="deterministic",
            )
    return None


def _try_event(
    thread: ReconstructedThread,
    thread_messages: list[dict[str, Any]],
    classification: ClassificationResult,
) -> ExtractionCandidate | None:
    if classification.lane not in {"travel", "financial", "legal"}:
        return None
    for msg in thread_messages:
        subject = str(msg.get("subject", "")).lower()
        if any(token in subject for token in EVENT_SUBJECT_TOKENS):
            locs = _locators([msg])
            return ExtractionCandidate(
                artifact_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"event:{msg['message_id']}")),
                artifact_type="event",
                source_thread_key=thread.thread_id,
                source_message_ids=(str(msg["message_id"]),),
                source_locators=locs,
                evidence_refs=locs,
                summary=f"{classification.lane.capitalize()} event: '{msg.get('subject', '')}' from {msg.get('from', '?')}.",
                confidence="medium",
                review_status="candidate",
                provenance="deterministic",
            )
    return None
