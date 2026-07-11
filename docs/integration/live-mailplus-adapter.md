# Live MailPlus Adapter Contract

The live adapter is `contract-only`. Fixture mode exercises its public boundary,
but `_fetch_messages()` intentionally returns an empty batch until issue #106
wires a real read-only MailPlus or IMAP transport. It is not integrated or
production-verified.

## Expected Configuration

`src/mailplus_intelligence/live_adapter.py` reads these environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `MAILPLUS_HOST` | yes | MailPlus API or IMAP host |
| `MAILPLUS_USER` | yes | Mailbox identity |
| `MAILPLUS_TOKEN` | yes | OAuth token or app password |
| `MAILPLUS_MAILBOX` | no | Mailbox/folder root, default `INBOX` |
| `MAILPLUS_PAGE_SIZE` | no | Batch size, default `50` |

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

## Worked IMAP Stub

```python
from mailplus_intelligence.live_adapter import LiveAdapterConfig
from mailplus_intelligence.sync import SyncBatch


def fetch_imap_metadata(config: LiveAdapterConfig, cursor: str = "") -> SyncBatch:
    messages = [
        {
            "fixture_id": "imap:123",
            "message_id": "<message@example.test>",
            "subject": "Example subject",
            "from": "sender@example.test",
            "to": ["operator@example.test"],
            "date": "2026-05-23T12:00:00Z",
            "mailbox": config.user,
            "folder": config.mailbox,
            "locator": {
                "export_id": "imap-demo",
                "uid": "123",
                "account": config.user,
            },
            "attachments": [],
        }
    ]
    next_checkpoint = messages[-1]["locator"]["uid"] if messages else cursor
    return SyncBatch(
        source_name=f"live:{config.user}",
        cursor=next_checkpoint,
        messages=tuple(messages),
    )
```

PRs are welcome for a real adapter once they preserve the metadata-only
boundary, fail closed on credential or locator drift, and include fixture-mode
tests that do not require live credentials.
