# Noise Suppression Policy

Suppression keeps low-value bulk and automated mail out of extraction by default
while preserving metadata searchability.

## Suppression Families

Suppress by default:

- newsletters and digests
- promotions and sales campaigns
- routine receipts
- automated CI, status, and monitoring notifications
- repetitive login, shipping, and account notices
- no-reply bulk messages with no human follow-up signal

## Signals

Rules may inspect:

- list and unsubscribe headers when exported
- `Auto-Submitted` or similar automation headers
- sender patterns such as `no-reply`, `newsletter`, `promo`, or `status`
- subject patterns such as sale, digest, receipt, status resolved, or webinar
- folder and label hints
- repetition frequency

## Behavior

Suppressed messages:

- remain in the metadata index
- remain searchable by sender, subject, date, folder, label, and locator
- do not enter semantic extraction by default
- may be promoted to review only when an explicit override marks the thread as
  important

## False Positive Review

Every suppression rule should have fixture coverage for false positives and
false negatives. Ambiguous cases should return `review_needed` rather than
silently suppressing important human mail.
