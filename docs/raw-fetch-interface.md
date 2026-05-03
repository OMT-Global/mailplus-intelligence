# On-Demand Raw Fetch Interface

Raw message access is an on-demand boundary. The metadata index should return
locators; exact source text should be fetched only when requested.

## Fetch Input

Fetch requests should provide:

- `locator_export_id`
- `locator_uid`
- `account`
- `mailbox`
- `folder_path`
- optional `message_id`
- optional `thread_key`

The fixture backend uses the same shape as a future live MailPlus adapter.

## Fixture Backend

The fixture backend may return synthetic raw text for tests. It should:

- require an exact locator match
- return source metadata with the synthetic body
- preserve the locator in the response
- avoid writing fetched text into memory, wiki, logs, or audit payloads

Fixture raw text must be synthetic. Real mailbox exports are not fixture inputs.

## Error Types

Fetch should fail with typed errors:

- `missing_locator`
- `moved_locator`
- `ambiguous_locator`
- `credential_gated`
- `backend_unavailable`

The live MailPlus adapter should return `credential_gated` when environment,
NAS, or DSM credentials are absent.

## Storage Rule

Fetch responses are transient by default. Long-term selected text caching is a
separate policy decision and must not happen implicitly through raw fetch.
