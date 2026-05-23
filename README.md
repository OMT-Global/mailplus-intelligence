# MailPlus Intelligence

MailPlus Intelligence is the intelligence layer for email, not the canonical mail warehouse.

## Core model

- **Canonical raw store:** the operator's MailPlus deployment
- **Structured recall layer:** metadata + thread index
- **Semantic layer:** selected high-value summaries, entities, obligations, and events
- **Durable memory surfaces:** wiki, `memory/`, `MEMORY.md`, and approved reminders/tasks

The system should **reference raw mail** from MailPlus rather than duplicating raw mail into long-term memory surfaces.

See [privacy, secrets, and redaction boundaries](docs/privacy-redaction-boundaries.md) for the raw-mail, metadata, cache, semantic-output, and durable-memory rules.

## Architecture

The canonical-store boundary is documented in
[`docs/architecture/canonical-store-boundary.md`](docs/architecture/canonical-store-boundary.md).
That document is the implementation guardrail for keeping MailPlus as the raw
archive while this repo stores only structured metadata and reviewed derived
intelligence.

### 1. Canonical archive: MailPlus

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

Start with the [fixture-mode quickstart](docs/quickstart.md) to seed a local
database, search fixture metadata, review extraction candidates, and run a
dry-run export without live MailPlus credentials.

## Runtime baseline

M0 uses a Python 3.12 package with SQLite-friendly local foundations.

Python is the initial runtime because indexing, classification, and extraction work will be data-heavy and benefits from the Python ecosystem. SQLite is the initial storage foundation for local metadata/thread indexing before any live MailPlus, DSM, or NAS access is introduced.

Local setup:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run the fast unit-test baseline:

```bash
bash scripts/ci/run-fast-checks.sh
```

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

## Agent execution

- [Agent execution playbook](docs/agent-execution/playbook.md)

## Operating rule

**MailPlus stores the mail. MailPlus Intelligence stores reviewed derived intelligence.**
