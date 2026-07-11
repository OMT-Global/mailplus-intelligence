# Live MailPlus Adapter Contract

The first supported transport is credential-gated IMAPS. `mpi sync run` opens
the configured mailbox read-only, records UIDVALIDITY plus the last processed
UID, and requests headers and flags only. It never requests RFC822 bodies, MIME
parts, or attachment payloads during metadata sync. Fixture mode exercises the
same boundary through an injected fake IMAP server; real connections remain an
explicit operator action and are not part of CI.

## Expected Configuration

`src/mailplus_intelligence/live_adapter.py` reads these environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `MAILPLUS_HOST` | yes | MailPlus API or IMAP host |
| `MAILPLUS_USER` | yes | Mailbox identity |
| `MAILPLUS_TOKEN` | yes | OAuth token or app password |
| `MAILPLUS_MAILBOX` | no | Mailbox/folder root, default `INBOX` |
| `MAILPLUS_PAGE_SIZE` | no | Batch size, default `50` |
| `MAILPLUS_PORT` | no | TLS port, default `993` |

Missing required values raise `LiveAdapterNotConfigured`; fixture-mode tests
should continue to treat that as a gated state, not a failure.

The runtime reads the invoking process environment only. It does not load
dotenv or other configuration files. `.env.example` documents canonical names,
but operators must export or process-inject values explicitly.

## SyncBatch Shape

Live ingestion must return the same `SyncBatch` shape as fixture ingestion:

- `source_name`: stable source identifier such as `live:<user>`
- `cursor`: checkpoint to commit after this batch succeeds
- `messages`: tuple of metadata-only message dictionaries

The adapter function may accept the prior checkpoint as an input parameter, but
`SyncBatch` has no `next_cursor` field. Its `cursor` value is the next checkpoint
that `run_sync_batch()` records only after the batch succeeds.

Each message should include source account/mailbox/folder, stable UID, message
ID, references/in-reply-to headers when present, sender/recipients, subject,
sent date, labels/flags, locator fields, and attachment metadata. It must not
include raw message bodies.

## Read-only IMAP Boundary

```python
from mailplus_intelligence.live_adapter import fetch_batch, load_live_config
from mailplus_intelligence.sync import run_sync_batch

config = load_live_config()
batch = fetch_batch(config, cursor="uidvalidity:42;uid:123")
result = run_sync_batch(connection, batch, dry_run=True)
```

The persisted cursor is `uidvalidity:<value>;uid:<last UID>`. A UIDVALIDITY
change fails closed and requires an explicit operator restart; it cannot be
mistaken for a normal pagination cursor. Authentication, malformed metadata,
and backend-unavailable paths are typed failures and never echo credentials.
