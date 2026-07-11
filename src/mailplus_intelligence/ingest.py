"""One metadata-only normalization, threading, and eligibility decision pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .classifier import classify_metadata
from .mapper import IndexRecord, MapperResult, map_fixture_messages
from .suppression import classify_noise_suppression
from .threading import ReconstructedThread, reconstruct_fixture_threads


@dataclass(frozen=True)
class IngestDecision:
    """The one persisted classification/suppression outcome for a source record."""

    fixture_id: str
    locator_export_id: str
    thread_key: str
    lane: str
    confidence: str
    suppression_action: str
    extraction_eligible: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PreparedIngest:
    """Normalized records, reconstructed threads, and their persisted decisions."""

    mapper: MapperResult
    records: tuple[IndexRecord, ...]
    threads: tuple[ReconstructedThread, ...]
    decisions: tuple[IngestDecision, ...]


def prepare_ingest(messages: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> PreparedIngest:
    """Derive normalized records and exactly one eligibility decision per record.

    Explicit MailPlus/header links establish threads before conservative subject
    fallback.  Human project labels override bulk classification, while a
    suppression decision always prevents automatic extraction.
    """

    source_messages = tuple(messages)
    mapper = map_fixture_messages(source_messages)
    raw_by_fixture_id = {
        str(message.get("fixture_id")): message
        for message in source_messages
        if isinstance(message, dict)
    }
    mapped_source = tuple(
        raw_by_fixture_id[record.fixture_id]
        for record in mapper.records
        if record.fixture_id in raw_by_fixture_id
    )
    threads = reconstruct_fixture_threads(mapped_source)
    thread_by_fixture_id = {
        fixture_id: thread
        for thread in threads
        for fixture_id in thread.message_fixture_ids
    }

    records: list[IndexRecord] = []
    decisions: list[IngestDecision] = []
    for record in mapper.records:
        source = raw_by_fixture_id[record.fixture_id]
        thread = thread_by_fixture_id[record.fixture_id]
        normalized = replace(record, thread_hint=thread.thread_id)
        suppression = classify_noise_suppression(source)
        classification = classify_metadata(normalized.subject, normalized.sender)
        project_override = "project" in {label.lower() for label in normalized.labels}
        lane = "project" if project_override else classification.lane
        eligible = (
            suppression.action == "allow"
            and (project_override or classification.extraction_allowed)
        )
        reason_codes = tuple(
            sorted(
                set(suppression.reasons)
                | {f"classification:{classification.reason_code}"}
                | ({"project-operator-override"} if project_override else set())
            )
        )
        records.append(normalized)
        decisions.append(
            IngestDecision(
                fixture_id=normalized.fixture_id,
                locator_export_id=normalized.locator_export_id,
                thread_key=thread.thread_id,
                lane=lane,
                confidence=thread.confidence,
                suppression_action=suppression.action,
                extraction_eligible=eligible,
                reason_codes=reason_codes,
            )
        )

    return PreparedIngest(mapper, tuple(records), threads, tuple(decisions))
