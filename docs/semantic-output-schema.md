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
- `created_at`
- `extractor_version`

`review_status` starts as `candidate` or `review_needed`. Promotion changes that
status through the review workflow; extraction itself must not write durable
memory or reminders.

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
