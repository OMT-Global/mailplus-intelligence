# Privacy, Secrets, and Redaction Boundaries

This project treats MailPlus on `omt-nas` as the canonical raw-mail system. MailPlus Intelligence may index, summarize, and promote derived intelligence, but it must not become a second raw-mail archive or a durable store for secrets.

## Data Classes

### Raw Mail

Raw mail is the complete message as stored by MailPlus, including bodies, full headers, attachments, inline images, quoted history, signatures, and embedded tracking or unsubscribe links.

Allowed artifacts:

- MailPlus message locators or stable references that let an approved operator fetch the source from MailPlus.
- Short source snippets used only during active review, when the snippet is necessary to verify a semantic output.
- Redacted, synthetic, or consent-approved examples in documentation and fixtures.

Forbidden artifacts:

- Full message bodies outside MailPlus.
- Attachment binaries or decoded attachment text in this repo, logs, fixtures, memory, or wiki pages.
- OAuth tokens, app passwords, session cookies, reset links, magic links, API keys, private keys, invoice payment links, or account recovery URLs copied from mail.
- Bulk exports such as `.eml`, `.mbox`, IMAP dumps, MailPlus backup archives, or mailbox sync caches.

### Metadata

Metadata is the structured recall layer used to find and reconstruct conversations without copying raw bodies.

Examples:

- `message-id`, `thread-id`, normalized reply references.
- Sender, recipients, mailbox, labels, folder, attachment flags, dates, and subject.
- MailPlus locator information when available.

Allowed artifacts:

- Index records needed for search, dedupe, thread reconstruction, and source attribution.
- Counts, timestamps, normalized identifiers, and classification labels.
- Redacted subjects when the original subject contains secrets, credentials, medical details, legal details, or personal identifiers that are not needed for retrieval.

Forbidden artifacts:

- Metadata fields that smuggle body content, attachment text, or raw quoted replies.
- Full recipient lists for sensitive personal, legal, financial, medical, or HR-like threads unless the list is needed for an approved operator workflow.
- Persistent identifiers that expose third-party private account IDs when a stable hashed or local surrogate identifier is sufficient.

### Selected Text Cache

Selected text cache is temporary, minimal text extracted from raw mail to support a specific classification, summary, review, or promotion decision.

Allowed artifacts:

- Narrow excerpts required to justify a derived output.
- Redacted text spans with source locators and expiration or refresh intent.
- Synthetic examples for tests and docs.

Forbidden artifacts:

- Long-lived body caches.
- Full threads copied into cache for convenience.
- Secrets, credentials, reset links, tracking links, payment links, or attachment text.
- Cache records without a source locator, review purpose, and disposal path.

Retention rule:

Selected text cache is working data. It should be short-lived, reviewable, and replaceable by a fresh MailPlus fetch. Anything worth keeping should be promoted as a semantic output or durable memory after review, not retained as raw text.

### Semantic Outputs

Semantic outputs are derived summaries, classifications, entities, obligations, decisions, events, and relationship notes produced from selected mail.

Allowed artifacts:

- Summaries that preserve operator value while stripping unnecessary raw text.
- Entity, project, account, event, and obligation records with source locators.
- Confidence, extraction time, and review status.
- Minimal quoted text only when needed to preserve legal, billing, travel, or decision meaning.

Forbidden artifacts:

- Verbatim thread copies disguised as summaries.
- Secret values, credential material, live links, or attachment payloads.
- Sensitive personal details that do not change the operator action or factual record.
- Unreviewed claims promoted as durable truth.

### Durable Memory

Durable memory includes wiki pages, `memory/`, `MEMORY.md`, approved reminders, tasks, and any long-lived knowledge surface.

Allowed artifacts:

- Reviewed semantic outputs with source locators back to MailPlus.
- Decisions, commitments, important dates, durable relationships, account facts, and action items.
- Redacted excerpts only when the exact wording materially matters.

Forbidden artifacts:

- Raw mail bodies, full headers, attachments, bulk mailbox exports, or selected text cache dumps.
- Secrets, credentials, session state, auth artifacts, recovery links, or app passwords.
- Automated notification noise, newsletters, marketing mail, or repetitive receipts unless transformed into a reviewed account, billing, warranty, travel, legal, or project fact.
- Private third-party details that are not needed for future recall.

## Artifact Rules

Allowed in the repo:

- Policy and architecture documentation.
- Synthetic fixtures that do not identify real people, accounts, domains, links, credentials, or messages.
- Redacted sample metadata where source values cannot be reconstructed.
- Templates for required environment variables without values.

Forbidden in the repo:

- Real raw mail, `.eml`, `.mbox`, IMAP/MailPlus exports, mailbox archives, attachment dumps, and screenshots of messages.
- Real credentials, session state, local auth files, cookies, tokens, password reset links, magic login links, OAuth URLs, private keys, and API keys.
- Production selected text caches or semantic output exports that have not passed promotion review.
- Machine-local caches, logs, database files, or generated stores that may contain raw message content.

## Fixture Redaction Rules

Fixtures must be synthetic by default. If a real-world shape is needed to reproduce parsing behavior, reduce it to the minimum structure and redact before committing.

Required redactions:

- Names: use stable synthetic names such as `Example Sender`.
- Email addresses: use reserved domains such as `sender@example.com`.
- Domains and URLs: use `example.com`, remove query strings, and replace live tokens with `[REDACTED_TOKEN]`.
- Message identifiers: use synthetic IDs such as `<fixture-message-001@example.com>`.
- Dates: shift or round unless the exact value is necessary for the scenario.
- Subjects: replace sensitive wording with neutral equivalents while preserving the parsing case.
- Attachment names: use generic names such as `invoice.pdf`; never include attachment contents.
- Secrets and recovery material: replace the whole value with `[REDACTED_SECRET]`, not a prefix or suffix.

Fixtures must not include:

- Real mailbox exports.
- Real quoted replies.
- Real unsubscribe, reset, login, tracking, billing, or payment links.
- Screenshots or OCR from real mail.

## Log Redaction Rules

Logs exist to explain behavior, not to preserve mail content.

Allowed log fields:

- Synthetic or hashed message identifiers.
- Thread identifiers, counts, durations, status codes, extraction class names, and review state.
- Source locator presence or absence, without raw body text.
- Error categories that identify the failure without dumping payloads.

Forbidden log fields:

- Raw bodies, selected text spans, attachments, full headers, full recipient lists for sensitive threads, secrets, tokens, reset links, magic links, payment links, or OAuth URLs.
- Prompt payloads or model responses that contain unreviewed raw mail text.
- Debug dumps of request, response, cache, or database records.

Operational rule:

When a failure needs payload-level inspection, reproduce it with a synthetic fixture or inspect the raw source in MailPlus under operator control. Do not promote payload dumps into logs.

## Promotion Review Checklist

Before moving anything from selected text cache or semantic output into durable memory, confirm:

- The output has a MailPlus source locator or other approved source reference.
- The output is derived intelligence, not a raw body copy.
- The minimum useful text has been retained.
- Secrets, credentials, recovery links, live auth URLs, payment links, tracking URLs, and attachment payloads are absent.
- Sensitive personal, legal, financial, medical, or HR-like details are present only when they are required for future operator action.
- Recipient and third-party details are minimized.
- The output has a clear future-use reason: decision, obligation, relationship, event, account fact, project context, or approved task/reminder.
- The reviewer can explain why this belongs in durable memory instead of staying discoverable through MailPlus.
- Any uncertainty is marked as unreviewed or needs-review rather than durable truth.

If any item fails, do not promote the artifact. Redact, summarize further, keep it as short-lived working data, or leave the raw source in MailPlus.
