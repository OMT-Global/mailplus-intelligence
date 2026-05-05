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
