# Live Adapter

`live_adapter.py` defines the boundary between the fixture-backed sync pipeline
and a future real MailPlus account. It produces the same `SyncBatch` type used
by `run_sync_batch()`, but the network transport and live CLI path are not yet
implemented.

## Configuration

Provide these values in the invoking process environment:

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

The application does not load dotenv files. `.env.example` is a naming template,
not an automatically loaded configuration source. Export values in the shell or
inject them through the process manager or secrets manager that starts `mpi`.

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

Status: `contract-only`. `_fetch_messages()` is a stub that returns an empty
list. `mpi doctor` therefore reports configuration separately from reachability,
authentication, and sync capability; only configuration can currently be `ok`.
The boundary may evolve when issue #106 adds and fake-server-tests a real
read-only transport.

## Security

- Inject credentials through the process environment or a secrets manager;
  never hard-code or commit them.
- Rotate `MAILPLUS_TOKEN` on any suspected exposure.
- The adapter is metadata-only; it must never fetch raw message bodies.
