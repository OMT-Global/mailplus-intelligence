# Capability Status And Forward Plan

## Scope

This document records capability evidence rather than treating a merged module
as proof of live integration. The near-term target is the Phase B single-account,
read-only alpha defined in issue #98. Its three pillars are:

1. **LLM-backed extraction** — richer semantic artifacts from classified threads
2. **Live account sync** — incremental, checkpointed sync from real MailPlus accounts
3. **Scheduler + job locking** — reliable recurring sync without overlapping runs

---

## Status Vocabulary

| Status | Meaning |
|---|---|
| `fixture-complete` | The behavior works end-to-end against synthetic fixtures in CI. |
| `contract-only` | Types and boundaries exist, but the external integration is a stub. |
| `integrated` | A real external dependency works in a controlled non-production environment. |
| `production-verified` | An approved operator has captured successful production evidence. |

No live MailPlus capability is currently `integrated` or
`production-verified`.

## Current Capability Status

| Module | Issue | Status |
|---|---|---|
| `sync.py` | #100 | `fixture-complete` |
| `extractor.py` | #6 | `fixture-complete` |
| `llm_extractor.py` cassette path | #70 | `fixture-complete` |
| `scheduler.py` SQLite lock path | #74 | `fixture-complete` |
| `live_adapter.py` | #106 | `contract-only` |
| `cli.py` fixture commands | #105 | `fixture-complete` |
| `index_writer.py` + search | #39 | `fixture-complete` |

---

## Architectural Decisions

### Metadata-only invariant
Raw message bodies are never fetched, stored, or transmitted.  All extraction
(deterministic and LLM) operates on subject, sender, date, folder, and
attachment metadata only.  This is enforced at the mapper layer.

### Deterministic-first, LLM-second
`extractor.py` runs first and produces candidates with `provenance="deterministic"`.
`llm_extractor.py` runs on the same threads and produces candidates with
`provenance="llm"`.  Downstream consumers can filter by provenance.

### Prompt caching
LLM extraction uses `cache_control: {"type": "ephemeral"}` on the shared
system prompt and per-thread context blocks.  This reduces token costs
significantly when processing multiple threads in one session.

### Offline CI gate
`llm_extractor.py` accepts a `cassette` dict mapping thread IDs to recorded
response strings.  CI passes a cassette so no Anthropic API calls are made.
Live calls happen only in environments where `ANTHROPIC_API_KEY` is set and
no cassette is provided.

### Job locking
`scheduler.py` uses a `scheduler_locks` SQLite table to prevent overlapping
runs.  Locks older than `LOCK_STALE_SECONDS` (300 s) are considered stale and
cleared automatically.

---

## Deferred Until The Read-Only Alpha Is Proven

- **MailPlus/IMAP client**: issue #106 replaces the live adapter stub after its
  Phase A dependencies close
- **Streaming LLM extraction**: use `client.messages.stream()` for large threads
- **Promotion workflow UI**: web interface for the queue review flow
- **Multi-account support**: per-account checkpoints and lane configuration
- **Relationship graph**: entity_update artifacts feeding a contact knowledge graph
- **Evaluation regressions**: nightly evaluation run against a golden fixture set
