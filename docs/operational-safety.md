# Operational Safety Requirements

Sync and extraction jobs need auditable behavior before live MailPlus access or
scheduled production runs are introduced.

## Checkpointing

Every import or sync source should maintain an inspectable checkpoint with:

- source name
- cursor or export batch identifier
- last successful run time
- last attempted run time when available
- schema or importer version
- dry-run versus apply mode

Reruns must be idempotent by the documented `locator_export_id` identity. A
replay should either report records as unchanged or explain exactly which records
were updated and why. Other uniqueness or constraint failures are errors, not
idempotent duplicates.

Index mutations and checkpoint advancement must share one transaction. A child
write, validation, or checkpoint failure leaves both the indexed data and cursor
at their prior committed state.

## Logging And Metrics

Logs should report:

- run start and end
- source and mode
- inserted, updated, unchanged, rejected, failed, and deleted-or-missing counts
- checkpoint changes
- parse or locator drift failures
- extraction and promotion candidate counts

Logs must not include raw message bodies or attachment contents.

## Failure Strategy

Failures should be typed so operators can distinguish:

- local dependency or fixture setup failures
- malformed export records
- duplicate message IDs
- missing or ambiguous locators
- stale checkpoints
- credential-gated live MailPlus access
- write or schema migration failures

Fatal mapper issues quarantine the record and block checkpoint advancement.
Non-fatal mapper warnings may accompany a successfully indexed record. Returned
quarantine metadata may contain source name, cursor, fixture identifier, reason
code, and a privacy-safe explanation, but never raw body or attachment content.
The five record outcome counts must add up to the number of source records read.

Credential-gated failures should stop clearly and not be retried as generic
network errors.

## Audit Trail

Audit events should preserve enough metadata to answer:

- what source records were read
- which index records changed
- which extraction candidates were produced
- which candidates were approved, rejected, corrected, or promoted
- which durable outputs can be rolled back

Audit entries should link to MailPlus or fixture locators instead of copying raw
mail text.

## Selected-Text Disposal

Expired selected text is overwritten in the active SQLite row and represented by
a privacy-safe tombstone plus append-only lifecycle events. Operators should
verify that active rows no longer contain `cached_text`, but must account for
SQLite WAL files, backups, filesystem snapshots, and storage-layer copies when
describing the larger retention boundary. Database, `-wal`, and `-shm` files are
restricted to owner-only permissions where the process can reach them. Backup
retention and snapshot destruction remain operator responsibilities.

Schedule `run_cache_disposal_job()` as part of the recurring local maintenance
loop. Its lock name is `selected-text-cache-disposal`; each run atomically
overwrites all expired selected text and records expiry/disposal events.

Do not log cache rows or model payloads while diagnosing expiry or egress
failures. Use event types, reason codes, keyed thread references, provider/model
labels, and declared data classes instead.

## Stale Run Detection

Recurring or manual jobs should report a stale state when expected checkpoints do
not advance, a previous run did not finish, or source exports are older than the
operator-requested window.
