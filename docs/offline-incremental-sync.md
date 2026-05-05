# Offline Incremental Sync Checkpoints

The first incremental sync loop runs against fixture or offline export batches.
It does not contact live MailPlus, DSM, or the NAS.

## Batch Model

Each batch should contain:

- `batch_id`
- source account and mailbox
- export creation time
- ordered metadata records
- deleted-or-missing markers when represented by the export
- cursor value for the next run

## Checkpoint State

Checkpoint state should record:

- source name
- last applied batch
- cursor
- importer version
- schema version
- dry-run or apply mode
- inserted, updated, skipped, and missing counts
- last success timestamp

## Rerun Behavior

An initial apply imports all valid records. Re-running the same batch should be
idempotent and report skipped records unless the normalized metadata changed.

A second batch may:

- insert new messages
- update moved messages or changed labels and flags
- mark exported missing records for review
- preserve locator history needed for audit review

## Dry Run

Dry-run mode computes the same planned mutations without changing the index or
advancing checkpoints. The report should be suitable for PR evidence and should
not include raw message bodies.

## Replay

Replay starts from a named checkpoint and reruns later batches in order. Replay
must fail closed when the requested checkpoint is missing, stale, or references a
schema version the current importer cannot read.
