# Live Export Integration

Production export to wiki pages, `memory/`, or reminders is v0.2 territory.
v0.1 only writes dry-run artifacts so reviewers can inspect candidate output
before anything durable changes.

## Required Guarantees

A live exporter must honor:

- provenance: every durable write keeps source thread, message IDs, locators,
  evidence references, confidence, and review status
- idempotency: rerunning the same approved candidate does not create duplicate
  wiki, memory, or reminder entries
- rollback: every write records enough target metadata to undo or supersede it
- review boundary: only `approved` or `corrected` candidates may leave the
  dry-run surface
- privacy boundary: raw message bodies and attachment payloads are never
  exported into durable memory surfaces

The dry-run exporter enforces the same queue boundary. It reloads the artifact
before writing, validates the complete canonical envelope, and requires the
latest append-only review event to match the queue revision and eligible state.
Detached or stale approved snapshots fail closed.

## Export Outbox

Every export target reserves one `export_outbox` row keyed by artifact ID,
approved revision, export type, and stable target key. That tuple produces a
deterministic idempotency key, so retrying the same revision cannot create a
second logical export. The outbox retains the authorizing review event, content
hash, target metadata, timestamps, failure code, and rollback note.

Dry-run filenames include the approved revision so rolling back an older export
cannot delete a newer corrected artifact at the same logical target.

When a reviewer moves an approved or corrected artifact to `rollback_needed`,
its exported outbox records move to the same state. Removal is performed
separately and then recorded as `rolled_back`; neither the artifact nor review
history is deleted.

See [promotion review workflow](../promotion-review-workflow.md) for the
human-review states that gate live writes.

## Target-Specific Notes

Wiki and `memory/` exporters should prefer stable page or note identifiers over
title matching. Reminder exporters should store the source artifact ID in the
target metadata when the target system allows it.

## Operator Flow

1. Run extraction and review candidates in the promotion queue.
2. Approve or correct only the artifacts that should become durable memory.
3. Run the exporter in dry-run mode and inspect the manifest.
4. Run the live exporter with an explicit target and rollback path.

The dry-run manifest includes the artifact revision, authorizing review event,
outbox ID, idempotency key, and rollback note for reconciliation.

Live export PRs are welcome once they include dry-run parity tests, rollback
evidence, and target-specific idempotency tests.
