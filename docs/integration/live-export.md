# Live Export Integration

Phase C in issue #98 may promote reviewed artifacts only to a local
Markdown/JSON `memory/` surface with rollback metadata. Remote wiki, task,
calendar, and reminder integrations remain deferred until after the vertical
slice proves the local boundary. The current `fixture-complete` path writes
dry-run artifacts so reviewers can inspect candidate output before any durable
change.

## Required Guarantees

A live exporter must honor:

- provenance: every durable write keeps source thread, message IDs, locators,
  evidence references, confidence, and review status
- idempotency: rerunning the same approved candidate does not create duplicate
  local or future remote entries
- rollback: every write records enough target metadata to undo or supersede it
- review boundary: only `approved` or `corrected` candidates may leave the
  dry-run surface
- privacy boundary: raw message bodies and attachment payloads are never
  exported into durable memory surfaces

See [promotion review workflow](../promotion-review-workflow.md) for the
human-review states that gate live writes.

## Target-Specific Notes

The Phase C local exporter should use stable artifact/revision identifiers in
paths and manifests. Future remote exporters should prefer stable page or object
identifiers over title matching and retain the source artifact ID in target
metadata when the target system allows it.

## Operator Flow

1. Run extraction and review candidates in the promotion queue.
2. Approve or correct only the artifacts that should become durable memory.
3. Run the exporter in dry-run mode and inspect the manifest.
4. Run the live exporter with an explicit target and rollback path.

The local Phase C exporter requires dry-run parity tests, rollback evidence, and
idempotency tests. Remote exporter PRs remain outside the current vertical slice.
