# Dry-Run Import Audit Events

Dry-run and apply import paths should emit structured audit events that are
readable by operators and stable enough for tests.

## Event Shape

Each event should include:

- `event_id`
- `event_type`
- `run_id`
- `source_name`
- `mode`: `dry_run` or `apply`
- `occurred_at`
- `checkpoint_before`
- `checkpoint_after`
- `counts`
- `locator_refs`
- `message`

Events must not include raw message bodies or attachment payloads.

## Promotion Review Events

Semantic review uses the append-only `review_events` table rather than the
import event shape above. Each record contains:

- stable `event_id` and `artifact_id`
- monotonically increasing `artifact_revision`
- `prior_status` and `new_status`
- explicit `reviewer_identity`
- timestamp, bounded notes, and an optional corrected summary

The original artifact summary and provenance remain in `promotion_queue` and
are protected by an immutable-envelope trigger. Corrections are new review
event data; they never overwrite the extracted summary. Legacy terminal queue
rows receive one deterministic `review.legacy_backfill` event attributed to
`legacy-migration`.

Review audit rows must not contain raw message bodies, prompt payloads, or
attachment content. They may contain a reviewer correction because that is the
reviewed derived artifact, not source mail text.

## Required Event Types

The first importer should cover:

- `import.started`
- `import.completed`
- `record.insert_planned`
- `record.update_planned`
- `record.skip_planned`
- `record.inserted`
- `record.updated`
- `record.skipped`
- `checkpoint.advance_planned`
- `checkpoint.advanced`
- `parse.failed`
- `replay.started`
- `replay.completed`

## Failure Events

Failure events should include a typed code such as `malformed_record`,
`duplicate_message_id`, `missing_locator`, `ambiguous_locator`, `stale_checkpoint`,
or `credential_gated`. They should include fixture IDs or locators instead of raw
mail text.

## Test Expectations

Tests should assert that success, dry-run, replay, and parse-failure paths emit
the expected event types and that audit payloads do not contain raw body fields.
