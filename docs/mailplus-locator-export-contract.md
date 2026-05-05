# MailPlus Locator And Export Contract

The locator contract defines how indexed metadata points back to canonical
messages in MailPlus without storing raw message bodies in this repo.

## Locator Fields

Every indexed message should carry the best available locator fields:

- `locator_export_id`: stable identifier for the export batch or fixture source
- `locator_uid`: source UID within the MailPlus mailbox or fixture export
- `account`: MailPlus account identity or fixture account name
- `mailbox`: MailPlus mailbox name
- `folder_path`: folder path at export time
- `message_id`: RFC message ID when present
- `thread_key`: normalized intelligence-layer thread key

`locator_export_id` and `locator_uid` are required for fixture-backed records.
`message_id` is required when available and should be treated as a dedupe input,
not the only source locator.

## Export Contract

Offline exports and future live adapters must provide metadata records with:

- source account, mailbox, and folder path
- source UID or equivalent stable per-message key
- message ID, references, and in-reply-to headers when present
- sender, recipients, subject, sent date, labels, flags, and attachment metadata
- moved/renamed-folder indicators when the source can report them
- an export checkpoint or cursor for incremental sync

The export must not include raw message bodies unless a caller explicitly uses a
fixture raw-fetch backend or a future credential-gated live fetch adapter.

## Drift And Failure Cases

The index should classify locator drift explicitly:

- `missing`: source message cannot be found by locator
- `moved`: UID exists but folder/mailbox identity changed
- `ambiguous`: multiple source messages match fallback fields
- `stale`: checkpoint is older than the source export snapshot
- `unavailable`: live MailPlus credentials or NAS access are not present

On drift, retrieval should fail closed with a typed error and preserve enough
metadata for operator review. It should not invent source text or silently use a
different message.

## Fetch Inputs

On-demand raw fetch should accept a locator object containing at least
`locator_export_id`, `locator_uid`, `account`, `mailbox`, and `folder_path`.
Message ID and thread key are supporting fields for verification and diagnostics.

Live MailPlus fetch remains a future credential-gated adapter. Fixture fetch can
use the same locator shape against synthetic fixture data.
