# Phase 2 Planning

## Scope

Phase 2 extends the metadata intelligence pipeline from the offline/fixture
baseline (Phase 1) to a production-capable system.  The three pillars are:

1. **LLM-backed extraction** — richer semantic artifacts from classified threads
2. **Live account sync** — incremental, checkpointed sync from real MailPlus accounts
3. **Scheduler + job locking** — reliable recurring sync without overlapping runs

---

## Completed in Phase 2 (this branch)

| Module | Issue | Status |
|---|---|---|
| `sync.py` | #3 | done |
| `extractor.py` | #6 | done |
| `llm_extractor.py` | #70 | done |
| `scheduler.py` | #74 | done |
| `live_adapter.py` | #71 | done |
| `cli.py` (search, queue, export, doctor) | #2, #4, #5, #7 | done |
| `index_writer.py` + search | #39 | done |

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

## Phase 3 Candidates

- **MailPlus API client**: replace `live_adapter._fetch_messages()` stub
- **Streaming LLM extraction**: use `client.messages.stream()` for large threads
- **Promotion workflow UI**: web interface for the queue review flow
- **Multi-account support**: per-account checkpoints and lane configuration
- **Relationship graph**: entity_update artifacts feeding a contact knowledge graph
- **Evaluation regressions**: nightly evaluation run against a golden fixture set
