# Relationship Update Candidates

Relationship extraction emits reviewable candidates for people, companies,
accounts, and projects. It is not a CRM replacement and does not promote durable
facts without review.

## Candidate Fields

Each candidate should include:

- candidate ID
- entity type
- stable entity key
- aliases
- candidate facts
- fact state: `new`, `changed`, or `inferred`
- source thread key
- source message IDs
- source locators
- evidence references
- confidence
- review status
- extractor version

## Deduplication

Stable keys should prefer explicit email addresses, domains, account IDs, or
project identifiers. When only names are available, candidates should be marked
lower confidence and review-needed.

## Fact Types

Initial relationship facts may include:

- role or title
- organization
- project association
- account ownership
- recent context summary
- last-contact metadata
- known aliases

## Review Boundary

Inferred or changed facts require review before promotion. The review queue must
preserve the original candidate, any corrected replacement, and all provenance
needed to trace the fact back to MailPlus or fixture locators.
