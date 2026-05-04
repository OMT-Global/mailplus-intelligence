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

Reruns must be idempotent. A replay should either produce no changes or explain
exactly which records were updated and why.

## Logging And Metrics

Logs should report:

- run start and end
- source and mode
- inserted, updated, skipped, failed, and deleted-or-missing counts
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

## Stale Run Detection

Recurring or manual jobs should report a stale state when expected checkpoints do
not advance, a previous run did not finish, or source exports are older than the
operator-requested window.
