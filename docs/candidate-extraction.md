# Obligation, Decision, And Event Candidate Extraction

Candidate extraction processes selected important threads only. It emits
review-needed artifacts and does not create reminders, memory entries, wiki
pages, or durable facts.

## Candidate Types

The first extractor should produce:

- obligations and follow-ups
- decisions
- deadlines
- travel events
- billing events
- legal events
- account and admin events

## Required Fields

Every candidate should include:

- candidate ID
- candidate type
- source thread key
- source message IDs
- source locators
- evidence references
- extracted text summary
- confidence
- review status
- extractor version

Review status defaults to `review_needed`.

## Processing Boundary

Ignored/noise lanes do not flow into extraction by default. Ambiguous
classification should stop at review rather than producing confident candidates.

## Non-Goals

This path must not:

- create reminders automatically
- write durable memory or wiki pages
- process suppressed noise classes
- store raw message bodies in logs or audit output
