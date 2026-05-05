# Selected-Message Text Cache Policy

The default policy is no durable raw message body cache. MailPlus remains the
canonical raw archive, and the intelligence layer stores metadata, locators, and
reviewed derived artifacts.

## Allowed Cases

Selected text may be cached only when all of these are true:

- the message is in an important lane such as VIP, project, admin, financial,
  travel, legal, or another explicitly reviewed category
- the text is needed for extraction, review, or reproducible fixture behavior
- the cache entry keeps a MailPlus locator and provenance
- retention is bounded by a documented purpose
- logs, memory, wiki, and audit output do not receive raw body dumps

Synthetic fixture messages may include synthetic body text for tests. Real mail
fixtures must be sanitized and minimized.

## Disallowed Cases

The system must not cache:

- newsletters, promotions, and marketing mail
- bulk notifications and automation logs
- repetitive receipts unless a narrow reviewed category allows it
- attachment binaries
- full mailbox exports
- messages fetched only for a one-time operator inspection

## Retention And Redaction

If a future implementation enables selected text cache entries, each entry
should record:

- source locator
- cache purpose
- classification lane
- created timestamp
- retention or expiry rule
- redaction state
- review status when human approval is required

Sensitive values should be redacted or omitted when they are not needed for the
specific extraction task.

## Fetch Versus Cache

When exact source text is needed, prefer on-demand fetch from MailPlus or a
fixture backend. Use cached selected text only when it is explicitly allowed by
this policy and improves reproducibility or review quality.

The schema field `raw_body_cached` is a policy marker, not permission to store
raw mail broadly.
