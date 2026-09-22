# Selected-Message Text Cache Policy

The default policy is no durable raw message body cache. MailPlus remains the
canonical raw archive, and the intelligence layer stores metadata, locators, and
reviewed derived artifacts.

## Allowed Cases

Selected text may be cached only when all of these are true:

- the message is in an important lane such as VIP, project, admin, financial,
  travel, legal, or another explicitly reviewed category
- the text is needed for extraction, review, or reproducible fixture behavior
- the selected excerpt is no larger than 16 KiB when encoded as UTF-8
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

Selected-text caching is implemented as an explicit operation. Every row records:

- source locator
- cache purpose
- classification lane
- created timestamp
- retention or expiry rule
- redaction state
- review status when human approval is required

Sensitive values should be redacted or omitted when they are not needed for the
specific extraction task.

TTL values are explicit integer seconds from `0` (immediate expiry, useful for
disposal verification) through 30 days. Negative, non-integer, or longer TTLs
fail closed; they are never silently converted into a longer retention period.
The default redaction state is `unreviewed`, never an implicit claim that a
caller-supplied excerpt has already been redacted. Callers must opt into
`redacted`, `minimal`, or `synthetic` only when that label is accurate.

When an entry expires, the implementation overwrites `cached_text` with an empty
value and retains only a lifecycle tombstone: locator, class, purpose,
redaction/provenance state, hashes, timestamps, and review requirement. Durable
events record write, read, miss, denial, expiry, and disposal using reason codes;
they never contain selected text.

Zero-second entries are overwritten in the same atomic write operation. Run
`run_cache_disposal_job()` from the recurring scheduler path to dispose other
expired rows even when they are never read again. Cache mutations and their
audit events share a savepoint, so an audit failure cannot leave unaudited text,
and a cache operation does not commit an unrelated caller transaction. Audited
cache APIs reject connections with an active transaction; use a clean dedicated
connection so read, miss, denial, expiry, and disposal events are durable when
the operation returns. Event rows store only one-way locator references, never
the source locator value itself.

SQLite overwrite is an application-level disposal boundary, not a promise of
forensic secure deletion. Previous bytes may remain temporarily in WAL pages,
filesystem snapshots, backups, SSD translation layers, or unmanaged replicas.
Keep the database and any `-wal`/`-shm` sidecars owner-only, allow SQLite to
checkpoint normally, expire backup generations on a bounded schedule, and never
claim disposal from snapshots the process does not control.

## Fetch Versus Cache

When exact source text is needed, prefer on-demand fetch from MailPlus or a
fixture backend. Use cached selected text only when it is explicitly allowed by
this policy and improves reproducibility or review quality.

The schema field `raw_body_cached` is a policy marker, not permission to store
raw mail broadly.
