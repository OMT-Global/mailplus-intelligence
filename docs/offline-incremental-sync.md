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
- inserted, updated, unchanged, rejected, failed, and missing counts
- last success timestamp

## Rerun Behavior

An initial apply imports all valid records. `locator_export_id` is the
idempotency identity: re-running an exact normalized record reports it as
`unchanged`, while metadata drift under that identity is an `updated` record.
A collision on another constraint, including mailbox plus UID, is a failure and
must never be reclassified as an idempotent duplicate.

A second batch may:

- insert new messages
- update moved messages or changed labels and flags
- mark exported missing records for review
- preserve locator history needed for audit review

## Reject And Quarantine Behavior

Mapper warnings, such as an optional malformed reference, do not reject an
otherwise usable record. Fatal mapper issues, such as missing required metadata,
produce a privacy-safe quarantine entry containing the source, cursor, fixture
identifier, code, and reason. The result never includes raw message or attachment
content.

A batch containing a rejected or failed record does not mutate index data or
advance its checkpoint. Correct the source metadata and replay the same cursor.
Every input is represented exactly once by the inserted, updated, unchanged,
rejected, or failed counts.

## Atomic Apply

Every accepted metadata record passes through one shared ingest decision before
the checkpoint advances: normalization, header-based thread reconstruction,
suppression/classification, then persistence. The indexed `ingest_decisions`
row is the source of truth for extraction eligibility; downstream extractors
must not classify the same record again.

Each observed locator is appended to `message_locator_history`. A move updates
the indexed current mailbox metadata while preserving the prior locator variant
for audit and review. Missing and deleted source states remain auditable rather
than deleting indexed metadata implicitly.

Normalized records are validated before mutation. Each record write uses a
savepoint, so a child-row failure removes its parent and relationship rows. The
batch's record mutations and checkpoint advancement then commit in one outer
transaction. If any record or checkpoint operation fails, both data and cursor
changes roll back.

## Dry Run

Dry-run mode computes the same inserted, updated, unchanged, rejected, and failed
plan as apply mode without changing the index, recording an attempt, or advancing
checkpoints. These are planned outcome counts; they are not claims that a dry-run
wrote records. The report is suitable for PR evidence and does not include raw
message bodies.

## Replay

Replay starts from a named checkpoint and reruns later batches in order. Replay
must fail closed when the requested checkpoint is missing, stale, or references a
schema version the current importer cannot read. A failed batch retains the prior
cursor, so the operator should repair or explicitly quarantine the rejected input
and replay that batch before processing later cursors.
