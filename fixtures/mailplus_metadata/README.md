# MailPlus Metadata Fixtures

This corpus is synthetic. It exists so indexing, threading, sync, and locator work can run offline without live MailPlus access or personal raw mail.

## Format

- `messages.json` contains metadata-only message records.
- `expected_threads.json` contains the expected normalized thread grouping for the records.
- Message bodies and attachment binaries are intentionally absent.
- `locator` values are placeholders that exercise mailbox, folder, UID, and stable export identifier handling.

## Coverage

The initial corpus covers:

- direct replies using `in_reply_to`
- multi-message threads using `references`
- forwarded mail with a distinct message ID
- duplicate message IDs
- malformed optional headers
- folder moves
- label and flag changes
- attachment metadata

Additions must stay fully synthetic and should include expected normalized outputs beside the input records.
