# Storage Backend Decision

Issue #9 chooses SQLite for the first metadata/thread index backend.

## Decision

Use SQLite as the v0 structured recall store for Phase 1 fixture and offline
export work.

SQLite fits the current repo shape because it is:

- available in the Python standard library
- shell-safe for fast PR checks
- portable for local agents and synthetic fixtures
- sufficient for metadata lookup, thread reconstruction, and checkpoint tests
- easy to replace behind a narrow repository/query contract later

## Initial Schema Direction

The concrete schema lives in
`src/mailplus_intelligence/migrations/001_metadata_schema_v0.sql` and is
summarized in `docs/schema-v0.md`.

The v0 model separates:

- mailboxes and folder identity
- messages and MailPlus locator fields
- normalized threads
- participants and message roles
- labels, flags, and attachment metadata
- message relationship edges
- sync checkpoints

Attachments are metadata-only. Raw message bodies and attachment binaries are
outside the schema unless a future selected-message cache policy explicitly
allows a narrow cached-text case.

## Query And Index Strategy

The initial indexes support the recall paths required before live MailPlus
integration:

- message ID exact lookup
- sender and recipient lookup through participant roles
- subject keyword lookup through normalized subject fields
- sent-date range lookup
- folder and mailbox lookup
- attachment presence filtering
- thread ID and relationship traversal
- locator-based source retrieval handoff

## Tradeoffs

SQLite is not the final answer if the index becomes multi-user, high-volume, or
requires concurrent writers. That is acceptable for Phase 1 because the near-term
goal is deterministic offline indexing and query behavior. A later Postgres move
should preserve the same message, thread, participant, locator, and checkpoint
contracts.
