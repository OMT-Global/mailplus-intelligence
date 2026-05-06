"""Dry-run promotion exporters — generates inspectable artifacts without writing to production surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .queue import QueueItem


@dataclass(frozen=True)
class ExportArtifact:
    """One reviewable export artifact linked to its approved candidate."""

    artifact_id: str
    export_type: str
    target_path: str
    content: str
    provenance: str
    locators: list[str]
    rollback_note: str | None


def export_approved_candidates(
    items: list["QueueItem"],
    output_dir: str | Path,
    *,
    dry_run: bool = True,
) -> list[ExportArtifact]:
    """Generate export artifacts for approved queue items.

    In dry_run mode (default) artifacts are written to output_dir but no
    production memory/wiki/reminder surfaces are modified.
    Every artifact includes provenance back to the source locators.
    """
    output = Path(output_dir)
    if not dry_run:
        raise RuntimeError("Live promotion is not implemented. Use dry_run=True.")

    artifacts: list[ExportArtifact] = []

    for item in items:
        if item.review_status not in {"approved", "corrected"}:
            continue

        summary = item.corrected_summary or item.summary
        artifact = _build_artifact(item, summary, output)
        artifacts.append(artifact)

        artifact_path = output / artifact.target_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(artifact.content, encoding="utf-8")

    manifest = _build_manifest(artifacts)
    manifest_path = output / "export-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return artifacts


def _build_artifact(item: "QueueItem", summary: str, output: Path) -> ExportArtifact:
    if item.artifact_type == "thread_summary":
        return _thread_summary_artifact(item, summary)
    elif item.artifact_type == "obligation":
        return _obligation_artifact(item, summary)
    elif item.artifact_type in {"entity_update", "decision", "event"}:
        return _generic_artifact(item, summary)
    else:
        return _generic_artifact(item, summary)


def _thread_summary_artifact(item: "QueueItem", summary: str) -> ExportArtifact:
    content = f"# Thread Summary\n\n**Thread:** {item.source_thread_key}\n**Confidence:** {item.confidence}\n\n{summary}\n\n---\n*Source locators: {', '.join(item.source_locators)}*\n*Artifact ID: {item.artifact_id}*\n"
    return ExportArtifact(
        artifact_id=item.artifact_id,
        export_type="memory_snippet",
        target_path=f"memory/thread-summaries/{item.artifact_id}.md",
        content=content,
        provenance=item.provenance,
        locators=item.source_locators,
        rollback_note=f"Delete memory/thread-summaries/{item.artifact_id}.md to revert.",
    )


def _obligation_artifact(item: "QueueItem", summary: str) -> ExportArtifact:
    content = json.dumps({
        "artifact_id": item.artifact_id,
        "type": "obligation",
        "thread": item.source_thread_key,
        "summary": summary,
        "confidence": item.confidence,
        "source_locators": item.source_locators,
        "provenance": item.provenance,
        "review_status": item.review_status,
        "reviewer_notes": item.reviewer_notes,
    }, indent=2)
    return ExportArtifact(
        artifact_id=item.artifact_id,
        export_type="obligation_proposal",
        target_path=f"memory/obligations/{item.artifact_id}.json",
        content=content,
        provenance=item.provenance,
        locators=item.source_locators,
        rollback_note=f"Delete memory/obligations/{item.artifact_id}.json to revert.",
    )


def _generic_artifact(item: "QueueItem", summary: str) -> ExportArtifact:
    content = json.dumps({
        "artifact_id": item.artifact_id,
        "type": item.artifact_type,
        "thread": item.source_thread_key,
        "summary": summary,
        "confidence": item.confidence,
        "source_locators": item.source_locators,
        "provenance": item.provenance,
        "review_status": item.review_status,
    }, indent=2)
    return ExportArtifact(
        artifact_id=item.artifact_id,
        export_type=item.artifact_type,
        target_path=f"memory/{item.artifact_type}/{item.artifact_id}.json",
        content=content,
        provenance=item.provenance,
        locators=item.source_locators,
        rollback_note=f"Delete memory/{item.artifact_type}/{item.artifact_id}.json to revert.",
    )


def _build_manifest(artifacts: list[ExportArtifact]) -> dict:
    return {
        "dry_run": True,
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "export_type": a.export_type,
                "target_path": a.target_path,
                "locators": a.locators,
                "rollback_note": a.rollback_note,
            }
            for a in artifacts
        ],
    }
