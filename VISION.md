# MailPlus Intelligence Vision

Version: 0.2

MailPlus Intelligence is the structured recall and semantic intelligence layer for email. Synology MailPlus remains the canonical raw mail archive; this repo indexes metadata, reconstructs threads, classifies lanes, suppresses noise, and promotes selected reviewed insights into durable memory surfaces.

The product is not a mailbox warehouse and not cloud mailbox automation. Its value is controlled extraction: keep raw messages and attachments in MailPlus, then derive enough metadata, summaries, obligations, decisions, events, and correspondence context to support search, planning, memory, and approved follow-up tasks.

## Who It Serves

- The operator who wants useful recall across MailPlus without duplicating raw mail into long-term memory.
- Agents that need fixture-backed thread, classification, and semantic-output contracts before acting on email-derived information.
- Future integration surfaces such as wiki pages, `memory/`, `MEMORY.md`, and reminders, where only reviewed derived intelligence should land.

## Current Product Boundary

- v0.1 is fixture-mode: metadata fixture sync, SQLite schema bootstrap, deterministic thread reconstruction, lane classification, noise suppression, deterministic semantic extraction, optional LLM extraction, promotion queue review, dry-run exporters, scheduler locks, CLI inspection, and `mpi doctor`.
- Live MailPlus/IMAP ingestion is documented but not connected.
- Production export to wiki, memory, or reminders is dry-run only until explicit live export work lands.
- Raw mail, attachments, and retention history remain in MailPlus.

## Product Principles

- Reference raw mail; do not copy it into durable memory surfaces.
- Metadata and derived semantic outputs must be bounded, reviewable, and redacted according to the privacy boundary.
- Fixture-bound validation is the default proof path, especially for malformed references, threading edge cases, classification, and extraction.
- Promotion is an explicit decision. High-value summaries and tasks should queue for review before becoming durable memory.
- Live adapters must preserve the canonical-store boundary and be testable without private mailbox content.

## Near-Term Direction

- Keep Phase 2 focused: live MailPlus adapter, live export contract, and promotion workflow without weakening raw-mail boundaries.
- Harden thread reconstruction, selected-message text cache policy, noise suppression, and semantic output schema.
- Improve `mpi doctor`, scheduler locks, and dry-run exporter evidence so operators can trust what would be promoted.
- Keep public docs, fixtures, and tests representative without exposing real mailbox contents.

## Non-Goals

- Do not become the canonical mail archive or attachment store.
- Do not require live private mail for routine tests.
- Do not auto-export obligations, summaries, or reminders without explicit approval.
- Do not leak raw message bodies, attachment contents, credentials, or private correspondents into docs, logs, fixtures, or PR text.
