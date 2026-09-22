"""Validated, idempotent dry-run promotion exporters."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from .queue import (
    EXPORT_ELIGIBLE_STATES,
    QueueItem,
    ReviewDecisionError,
    get_item,
    get_review_history,
    mark_outbox_exported,
    mark_outbox_failed,
    reserve_outbox,
)
from .semantic_contract import validate_semantic_artifact


class ExportEligibilityError(ValueError):
    """Raised when provenance or the latest review cannot authorize export."""


@dataclass(frozen=True)
class ExportArtifact:
    """One reviewable export artifact linked to its approved revision."""

    artifact_id: str
    artifact_revision: int
    review_event_id: str
    export_type: str
    target_path: str
    content: str
    provenance: str
    locators: list[object]
    rollback_note: str | None
    outbox_id: str | None = None
    idempotency_key: str | None = None


def export_approved_candidates(
    items: list[QueueItem],
    output_dir: str | Path,
    *,
    connection: sqlite3.Connection,
    dry_run: bool = True,
) -> list[ExportArtifact]:
    """Validate and export approved queue revisions with durable identity.

    The queue snapshot is reloaded from ``connection`` before writing. This
    prevents a stale approval from leaving the review boundary.
    """

    output = Path(output_dir)
    if not dry_run:
        raise RuntimeError("Live promotion is not implemented. Use dry_run=True.")

    artifacts: list[ExportArtifact] = []
    for supplied_item in items:
        if supplied_item.review_status not in EXPORT_ELIGIBLE_STATES:
            continue

        item = _current_export_item(connection, supplied_item)
        summary = item.corrected_summary or item.summary
        artifact = _build_artifact(item, summary)
        content_hash = hashlib.sha256(artifact.content.encode("utf-8")).hexdigest()
        try:
            outbox = reserve_outbox(
                connection,
                item,
                export_type=artifact.export_type,
                target_key=artifact.target_path,
                content_hash=content_hash,
                rollback_note=artifact.rollback_note,
            )
        except ReviewDecisionError as exc:
            raise ExportEligibilityError(str(exc)) from exc
        if outbox.state in {"rollback_needed", "rolled_back"}:
            raise ExportEligibilityError(
                f"artifact {item.artifact_id} export is blocked by rollback state"
            )

        artifact = replace(
            artifact,
            outbox_id=outbox.outbox_id,
            idempotency_key=outbox.idempotency_key,
        )
        artifact_path = output / artifact.target_path
        if outbox.state == "exported":
            if not artifact_path.is_file() or _sha256_path(artifact_path) != content_hash:
                raise ExportEligibilityError(
                    f"exported target is missing or changed: {artifact.target_path}"
                )
        else:
            try:
                _atomic_write_text(artifact_path, artifact.content)
            except OSError:
                try:
                    mark_outbox_failed(
                        connection,
                        outbox.outbox_id,
                        failure_code="write_failed",
                    )
                except ReviewDecisionError:
                    # Preserve the filesystem failure if a concurrent review
                    # changed the outbox before failure recording.
                    pass
                raise

            try:
                mark_outbox_exported(
                    connection,
                    outbox.outbox_id,
                    target_metadata={"mode": "dry_run", "target_path": artifact.target_path},
                )
            except ReviewDecisionError as exc:
                _unlink_if_hash(artifact_path, content_hash)
                raise ExportEligibilityError(str(exc)) from exc
        artifacts.append(artifact)

    manifest = _build_manifest(artifacts)
    manifest_path = output / "export-manifest.json"
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2))
    return artifacts


def _current_export_item(
    connection: sqlite3.Connection,
    supplied_item: QueueItem,
) -> QueueItem:
    current = get_item(connection, supplied_item.artifact_id)
    if current is None:
        raise ExportEligibilityError(f"artifact not found: {supplied_item.artifact_id}")
    if current.revision != supplied_item.revision:
        raise ExportEligibilityError(
            f"stale export snapshot for {current.artifact_id}: supplied revision "
            f"{supplied_item.revision}, current revision {current.revision}"
        )
    if current.review_status not in EXPORT_ELIGIBLE_STATES:
        raise ExportEligibilityError(
            f"artifact {current.artifact_id} is not export eligible: {current.review_status}"
        )

    errors = validate_semantic_artifact(current.semantic_dict())
    if errors:
        raise ExportEligibilityError(
            f"artifact {current.artifact_id} has incomplete provenance: {'; '.join(errors)}"
        )

    history = get_review_history(connection, current.artifact_id)
    latest = history[-1] if history else None
    if (
        latest is None
        or latest.event_id != current.latest_review_event_id
        or latest.artifact_revision != current.revision
        or latest.new_status != current.review_status
        or latest.reviewer_identity != current.reviewer_identity
        or latest.reviewer_notes != current.reviewer_notes
        or latest.corrected_summary != current.corrected_summary
        or latest.occurred_at != current.decided_at
    ):
        raise ExportEligibilityError(
            f"artifact {current.artifact_id} lacks a matching latest review decision"
        )
    if current.review_status == "corrected" and not current.corrected_summary:
        raise ExportEligibilityError(
            f"corrected artifact {current.artifact_id} has no correction"
        )
    return current


def _build_artifact(item: QueueItem, summary: str) -> ExportArtifact:
    if item.artifact_type == "thread_summary":
        return _thread_summary_artifact(item, summary)
    if item.artifact_type == "obligation":
        return _obligation_artifact(item, summary)
    return _generic_artifact(item, summary)


def _thread_summary_artifact(item: QueueItem, summary: str) -> ExportArtifact:
    provenance = json.dumps(_provenance_payload(item), indent=2)
    content = (
        "# Thread Summary\n\n"
        f"**Thread:** {item.source_thread_key}\n"
        f"**Confidence:** {item.confidence}\n\n"
        f"{summary}\n\n"
        "---\n"
        f"Provenance:\n```json\n{provenance}\n```\n"
    )
    target_path = f"memory/thread-summaries/{item.artifact_id}-r{item.revision}.md"
    return ExportArtifact(
        artifact_id=item.artifact_id,
        artifact_revision=item.revision,
        review_event_id=_review_event_id(item),
        export_type="memory_snippet",
        target_path=target_path,
        content=content,
        provenance=item.provenance,
        locators=item.source_locators,
        rollback_note=f"Delete {target_path} to revert.",
    )


def _obligation_artifact(item: QueueItem, summary: str) -> ExportArtifact:
    content = json.dumps(
        {
            **_provenance_payload(item),
            "type": "obligation",
            "summary": summary,
        },
        indent=2,
    )
    target_path = f"memory/obligations/{item.artifact_id}-r{item.revision}.json"
    return ExportArtifact(
        artifact_id=item.artifact_id,
        artifact_revision=item.revision,
        review_event_id=_review_event_id(item),
        export_type="obligation_proposal",
        target_path=target_path,
        content=content,
        provenance=item.provenance,
        locators=item.source_locators,
        rollback_note=f"Delete {target_path} to revert.",
    )


def _generic_artifact(item: QueueItem, summary: str) -> ExportArtifact:
    content = json.dumps(
        {
            **_provenance_payload(item),
            "type": item.artifact_type,
            "summary": summary,
        },
        indent=2,
    )
    target_path = f"memory/{item.artifact_type}/{item.artifact_id}-r{item.revision}.json"
    return ExportArtifact(
        artifact_id=item.artifact_id,
        artifact_revision=item.revision,
        review_event_id=_review_event_id(item),
        export_type=item.artifact_type,
        target_path=target_path,
        content=content,
        provenance=item.provenance,
        locators=item.source_locators,
        rollback_note=f"Delete {target_path} to revert.",
    )


def _provenance_payload(item: QueueItem) -> dict[str, object]:
    return {
        "artifact_id": item.artifact_id,
        "artifact_revision": item.revision,
        "review_event_id": _review_event_id(item),
        "thread": item.source_thread_key,
        "original_summary": item.summary,
        "source_message_ids": item.source_message_ids,
        "source_locators": item.source_locators,
        "evidence_refs": item.evidence_refs,
        "confidence": item.confidence,
        "provenance": item.provenance,
        "extractor_version": item.extractor_version,
        "model_version": item.model_version,
        "rule_version": item.rule_version,
        "artifact_created_at": item.created_at,
        "initial_review_status": item.initial_review_status,
        "review_status": item.review_status,
        "reviewer_identity": item.reviewer_identity,
        "reviewed_at": item.decided_at,
    }


def _review_event_id(item: QueueItem) -> str:
    if not item.latest_review_event_id:
        raise ExportEligibilityError(
            f"artifact {item.artifact_id} has no latest review event"
        )
    return item.latest_review_event_id


def _atomic_write_text(path: Path, content: str) -> None:
    """Durably replace one export file without exposing partial content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unlink_if_hash(path: Path, expected_hash: str) -> None:
    try:
        if path.is_file() and _sha256_path(path) == expected_hash:
            path.unlink()
    except OSError:
        pass


def _build_manifest(artifacts: list[ExportArtifact]) -> dict[str, object]:
    return {
        "dry_run": True,
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "artifact_revision": artifact.artifact_revision,
                "review_event_id": artifact.review_event_id,
                "export_type": artifact.export_type,
                "target_path": artifact.target_path,
                "locators": artifact.locators,
                "outbox_id": artifact.outbox_id,
                "idempotency_key": artifact.idempotency_key,
                "rollback_note": artifact.rollback_note,
            }
            for artifact in artifacts
        ],
    }
