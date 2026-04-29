# MailPlus Intelligence

MailPlus Intelligence is the intelligence layer for email, not the canonical mail warehouse.

## Core model

- **Canonical raw store:** MailPlus on `omt-nas`
- **Structured recall layer:** metadata + thread index
- **Semantic layer:** selected high-value summaries, entities, obligations, and events
- **Durable memory surfaces:** wiki, `memory/`, `MEMORY.md`, and approved reminders/tasks

The system should **reference raw mail** from MailPlus rather than duplicating raw mail into long-term memory surfaces.

## Architecture

### 1. Canonical archive: MailPlus on `omt-nas`

MailPlus remains the source of truth for:

- raw message storage
- attachments
- threading truth
- retention/compliance/history

### 2. Email index layer

The index layer should cover all mail metadata needed for fast retrieval and thread reconstruction, including:

- `message-id`
- `thread-id`
- `from` / `to` / `cc`
- `subject`
- `date`
- mailbox / folder / labels
- attachment flags
- normalized thread relationships
- MailPlus locator information when available

This layer exists for:

- fast filtering
- thread reconstruction
- dedupe
- source discovery such as “find all mail from X about Y”

### 3. Semantic extraction layer

Only selected, high-value mail should be promoted into derived intelligence such as:

- thread summaries
- people/company relationship summaries
- commitments / obligations
- decisions made in email
- travel / billing / legal / account events
- project correspondence summaries

Those distilled outputs can then feed:

- wiki pages
- `memory/`
- `MEMORY.md`
- future entity/concept pages
- reminders/tasks when explicitly approved

## What should not go into memory

Avoid dumping:

- all raw email bodies
- newsletters, marketing, and promotions
- bulk notifications
- automated logs
- repetitive receipts unless categorized
- attachment binaries

That would poison recall quality and blur the canonical/archive boundary.

## Recommended starting point

This repo is targeting the **medium** architecture first:

- full metadata/thread index
- incremental sync
- selective semantic extraction
- wiki/entity promotion
- raw email remains only in MailPlus

This gives high value without memory bloat or premature overbuilding.

## Phase 1 goals

Phase 1 should support practical operator questions like:

- What’s my history with this person?
- Did I already commit to this?
- What admin, travel, financial, or legal follow-ups are pending?

## Roadmap status

The current roadmap is tracked in GitHub issues for this repository.

Primary epics include:

- architecture boundary and canonical-store model
- metadata/thread indexing
- incremental sync/export
- search and on-demand raw fetch
- classification lanes
- semantic extraction
- memory/wiki promotion
- phase-1 medium-architecture delivery

## Operating rule

**MailPlus stores the mail. Pheidon stores the intelligence.**
