# Live Adapter

`live_adapter.py` implements credential-gated, read-only IMAPS metadata
fetching. `mpi sync run` calls `fetch_batch()` and passes its `SyncBatch` to
`run_sync_batch()`. Each invocation fetches one bounded page of headers and
flags; it does not fetch message bodies or attachment payloads.

## Configuration

Provide these values in the invoking process environment:

| Variable | Required | Description |
|---|---|---|
| `MAILPLUS_HOST` | yes | IMAPS hostname |
| `MAILPLUS_USER` | yes | Mailbox address |
| `MAILPLUS_TOKEN` | yes | Password or app password accepted by IMAP LOGIN |
| `MAILPLUS_MAILBOX` | no | Folder to sync (default `INBOX`) |
| `MAILPLUS_PAGE_SIZE` | no | Messages per batch, 1–1000 (default `50`) |
| `MAILPLUS_PORT` | no | TLS port, 1–65535 (default `993`) |

If any required variable is absent, `load_live_config()` raises
`LiveAdapterNotConfigured`. Automated tests inject synthetic configuration and
a fake IMAP client; they do not connect to a real mailbox.

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

Status: implemented with fake-server coverage; real MailPlus integration and
production operation remain unverified. Existing tests verify read-only mailbox
selection, header-only requests, flags, UIDVALIDITY cursor construction,
invalidation, and authentication failure.

Resume requires passing the prior cursor to `fetch_batch()` or supplying
`mpi sync run --cursor`; the CLI does not automatically read the saved
checkpoint. The cursor records UIDVALIDITY and the last processed UID. See the
[adapter contract](integration/live-mailplus-adapter.md) for details.

`mpi doctor` checks local configuration without network access. Reachability,
authentication, and sync capability remain `gated` in doctor because it never
probes those capabilities. Operators must run an explicit sync to verify them.

## Security

- Inject credentials through the process environment or a secrets manager;
  never hard-code or commit them.
- Rotate `MAILPLUS_TOKEN` on any suspected exposure.
- The adapter is metadata-only; it must never fetch raw message bodies.
