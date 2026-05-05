# Canonical Store Boundary

MailPlus Intelligence treats the operator's MailPlus deployment as the canonical
raw mail archive. This repository owns the derived intelligence layer around that
archive: metadata indexing, retrieval workflows, selected semantic extraction,
and reviewed promotion into memory or wiki surfaces.

## Source Of Truth

MailPlus remains authoritative for:

- raw message bodies
- attachments
- mailbox and folder retention
- message threading truth
- compliance and historical archive behavior

The intelligence layer may store structured metadata, thread relationships,
locators, audit records, and reviewed derived facts. It must not mirror the
full raw mailbox into memory, wiki pages, fixtures, or durable logs.

## Reference, Do Not Duplicate

Indexed records should point back to MailPlus through stable locators. When an
operator needs exact source text, the system should fetch the message on demand
from MailPlus or a fixture backend in tests. Derived summaries and candidates
must retain provenance so reviewers can trace every promoted fact back to the
canonical message or thread.

## Durable Memory Rule

Durable memory surfaces may receive only distilled, reviewed intelligence:

- durable relationship facts
- decisions and commitments
- obligations and follow-ups
- account, travel, legal, billing, or project events
- high-signal thread summaries

They must not receive raw email dumps, attachment binaries, newsletters,
marketing mail, repetitive receipts, or bulk automation noise.

## Boundary Enforcement

Implementation work should keep these checks visible:

- fixture data stays synthetic or sanitized
- logs and audit events exclude raw message bodies
- selected-message text caches require explicit policy
- live MailPlus and DSM access remains credential-gated
- promotion into memory, wiki, or reminders requires review gates

This boundary lets MailPlus keep archival truth while MailPlus Intelligence
provides high-signal recall and operator intelligence.
