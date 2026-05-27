# Live MailPlus Adapter Integration

The live adapter is v0.2 territory. v0.1 ships the stable boundary and fixture
mode, but `_fetch_messages()` intentionally returns an empty batch until a real
MailPlus or IMAP client is wired in.

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

## SyncBatch Shape

Live ingestion must return the same `SyncBatch` shape as fixture ingestion:

- `source_name`: stable source identifier such as `mailplus:<user>`
- `cursor`: previous cursor supplied by the scheduler or checkpoint
- `next_cursor`: cursor for the next incremental sync
- `messages`: list of metadata-only message dictionaries

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
    return SyncBatch(
        source_name=f"mailplus:{config.user}",
        cursor=cursor,
        next_cursor="123",
        messages=messages,
    )
```

PRs are welcome for a real adapter once they preserve the metadata-only
boundary, fail closed on credential or locator drift, and include fixture-mode
tests that do not require live credentials.
