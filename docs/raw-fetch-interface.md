# On-Demand Raw Fetch Interface

Raw message access is an on-demand boundary. The metadata index should return
locators; exact source text should be fetched only when requested.

## Implemented Boundary

`mailplus_intelligence.source_fetch` implements the fixture-first boundary. An
operator creates a `SourceFetchRequest` with one complete `SourceLocator`, an
allowed purpose (`extraction` or `review`), and the sole currently approved data
class (`minimized-source`). The request is never inferred from search results or
metadata sync.

`fetch_selected_source()` returns a context-managed `TransientSource`. Its raw
buffer is overwritten and cleared at context exit. Python cannot guarantee that
all string copies, crash dumps, swap, or process snapshots are zeroized; this is
best-effort disposal, not a claim of perfect memory erasure.

`extract_minimized_source()` runs deterministic, in-process extraction only. It
uses minimized text and stores only the original metadata locator plus a SHA-256
evidence reference in a review-required artifact. Cloud or local model egress
of source text is not implemented and remains blocked unless a separately
reviewed provider-policy extension authorizes it.

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

The live backend currently returns `credential_gated`; it remains a deliberate
dependency seam until the approved read-only IMAP adapter is merged and
configured. Fixture tests cover `missing_locator`, `moved_locator`,
`credential_gated`, and `backend_unavailable` without real mailbox content.

## Storage Rule

Fetch responses are transient by default. Long-term selected text caching is a
separate policy decision and must not happen implicitly through raw fetch.

## Operator Recipe

```python
with fetch_selected_source(request, fixture_backend) as source:
    candidates = extract_minimized_source(source)
```

Use the original MailPlus locator to review any candidate. Do not print the
buffer, pass it to an unapproved model, or call `cache_write` as part of fetch.
