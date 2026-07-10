# Semantic Output Schema

Semantic extraction emits candidates, not approved durable facts. Every artifact
must preserve enough provenance for review and correction.

## Common Fields

All semantic artifacts should include:

- `artifact_id`
- `artifact_type`
- `source_thread_key`
- `source_message_ids`
- `source_locators`
- `evidence_refs`
- `summary`
- `confidence`
- `review_status`
- `provenance`
- `created_at`
- `extractor_version`
- `model_version`
- `rule_version`

`review_status` starts as `candidate` or `review_needed`. Promotion changes that
status in queue state and append-only review events; the extraction-time value
inside the artifact never changes. Extraction itself must not write durable
memory or reminders.

The canonical envelope is immutable after enqueue. `source_message_ids`,
`source_locators`, and `evidence_refs` are separate fields and must round-trip
without being packed into `provenance`. `provenance` is either `deterministic`
or `llm`; deterministic artifacts require `rule_version`, LLM artifacts require
`model_version`, and every artifact requires `extractor_version` and a
timezone-aware `created_at`.

String locators are opaque identifiers without whitespace. Structured locators
use only the documented account, provider, mailbox/folder, export-ID, and UID
fields; arbitrary extension keys, nested payloads, non-finite numbers, and
credential-shaped values are rejected. Evidence references are single-line,
privacy-safe references or short snippets of at most 256 characters. Unknown
top-level fields are rejected rather than silently discarded.

## Artifact Types

### Thread Summary

Captures the distilled point of a selected thread:

- participants
- timeline summary
- current state
- open questions
- source locators

### Entity Update

Captures people, company, account, or project relationship facts:

- entity key and aliases
- explicit facts
- inferred facts
- changed facts
- last contact metadata
- provenance for each fact

### Obligation

Captures commitments and follow-ups:

- actor
- obligation text
- due date or timing hint
- counterparty
- status
- source evidence

### Decision

Captures decisions made in mail:

- decision statement
- deciding party
- effective date when known
- options rejected when visible
- evidence locator

### Event

Captures travel, billing, legal, admin, account, or project events:

- event category
- event time or date range
- involved entities
- operational impact
- source evidence

## Candidate Versus Approved Facts

Candidates are reviewable extraction outputs. Approved facts are durable outputs
that have passed a promotion workflow. The schema must keep those states
distinct so memory, wiki, and reminder surfaces do not receive unreviewed
material.

## Provenance Requirements

Every artifact must point back to at least one MailPlus locator or fixture
locator. Evidence references should be short snippets, line identifiers, or
field references, not raw body dumps.

Rows migrated from the pre-v4 queue use `provenance="legacy"`, preserve the old
JSON `provenance` value as `evidence_refs` when it was a valid array, and use
`extractor_version="legacy-unknown"`. Because the old schema discarded source
message IDs and extractor/model/rule versions, those rows remain auditable but
cannot be exported until re-extracted into a complete canonical envelope.
