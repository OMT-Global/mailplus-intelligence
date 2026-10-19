# Live MailPlus Adapter Contract

The first supported transport is credential-gated IMAPS. `mpi sync run` opens
the configured mailbox read-only, records UIDVALIDITY plus the last processed
UID, and requests headers and flags only. It never requests RFC822 bodies, MIME
parts, or attachment payloads during metadata sync. Automated adapter tests
exercise the same boundary through an injected fake IMAP client; real connections
remain an explicit operator action and are not part of CI.

Each invocation fetches one bounded page. To resume, pass the saved cursor with
`--cursor`; the CLI does not automatically load it from the database. Fake-server
coverage does not establish real MailPlus integration or production verification.

## Expected Configuration

`src/mailplus_intelligence/live_adapter.py` reads these environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `MAILPLUS_HOST` | yes | IMAPS host |
| `MAILPLUS_USER` | yes | Mailbox identity |
| `MAILPLUS_TOKEN` | yes | Password or app password accepted by IMAP LOGIN |
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

- `source_name`: stable source identifier `imap:<mailbox>`
- `cursor`: checkpoint to commit after this batch succeeds
- `messages`: tuple of metadata-only message dictionaries

The adapter function may accept the prior checkpoint as an input parameter, but
`SyncBatch` has no `next_cursor` field. Its `cursor` value is the next checkpoint
that `run_sync_batch()` records only after the batch succeeds.

Each returned message includes message ID, references/in-reply-to headers when
present, sender/recipients, subject, sent date, flags, and source
account/mailbox/folder/UID locator fields. The current IMAPS adapter emits empty
labels and attachment metadata lists; it does not discover attachments. Raw
message bodies are excluded.

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
