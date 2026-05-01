# Metadata Schema v0

Schema v0 uses SQLite as the interim structured recall store selected by the M0 runtime baseline. It is designed for offline fixture and export work before live MailPlus credentials are introduced.

## Tables

- `mailboxes`: account, mailbox, and folder identity.
- `threads`: normalized thread keys, subject normalization, and confidence.
- `messages`: metadata records, locator fields, attachment flag, and raw-cache boundary.
- `participants` and `message_participants`: sender and recipient relationships.
- `labels` / `message_labels` and `flags` / `message_flags`: MailPlus labels and flags.
- `attachments`: metadata only; no binary payloads.
- `message_relationships`: `references` and `in-reply-to` edges.
- `sync_checkpoints`: resumable fixture/export cursor state.

## Index Plan

The first indexes cover message ID, date, subject, thread, folder, participant email, role, and attachment lookups. Those support the initial recall paths for sender, subject keyword, date range, folder, attachment presence, and thread ID.

## Boundaries

The schema does not store raw message bodies or attachment binaries. `raw_body_cached` is present only as an explicit policy marker for future selected-message cache decisions.
