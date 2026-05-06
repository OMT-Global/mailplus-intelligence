# Live Adapter

`live_adapter.py` bridges the fixture-backed sync pipeline to a real MailPlus
account.  It produces the same `SyncBatch` type used by `run_sync_batch()`, so
no other code changes when switching from fixtures to live.

## Configuration

Copy `.env.example` to `.env` (never commit `.env`) and fill in:

| Variable | Required | Description |
|---|---|---|
| `MAILPLUS_HOST` | yes | IMAP or MailPlus API hostname |
| `MAILPLUS_USER` | yes | Mailbox address |
| `MAILPLUS_TOKEN` | yes | OAuth2 bearer token or app password |
| `MAILPLUS_MAILBOX` | no | Folder to sync (default `INBOX`) |
| `MAILPLUS_PAGE_SIZE` | no | Messages per batch (default `50`) |

If any required variable is absent, `load_live_config()` raises
`LiveAdapterNotConfigured`.  CI omits these variables deliberately, so the live
path is never exercised in automated tests.

## Gate Pattern

```python
from mailplus_intelligence.live_adapter import LiveAdapterNotConfigured, fetch_batch, load_live_config

try:
    config = load_live_config()
except LiveAdapterNotConfigured as exc:
    print(f"Live adapter not available: {exc}")
    raise SystemExit(1)

batch = fetch_batch(config, cursor="")
```

## Current Status

`_fetch_messages()` is a stub that returns an empty list.  Replace it with the
MailPlus API client call once the client library is available.  The public
interface (`fetch_batch`, `load_live_config`) is stable and will not change.

## Security

- Store credentials in `.env` or a secrets manager — never hard-code them.
- Rotate `MAILPLUS_TOKEN` on any suspected exposure.
- The adapter is metadata-only; it must never fetch raw message bodies.
