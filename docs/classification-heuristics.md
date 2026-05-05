# Classification Heuristics And Evaluation

The first classification system should be deterministic, explainable, and
fixture-backed before any model-assisted classifier is introduced.

## Lanes

Initial lanes are:

- `vip`
- `project`
- `admin`
- `financial`
- `travel`
- `legal`
- `ignore_noise`
- `review_needed`

`review_needed` is the safe result when rules conflict or confidence is too low.

## Heuristic Inputs

Rules may use metadata and explicitly allowed selected text fields:

- sender and recipient address
- known VIP or project domains
- subject tokens
- folder and label hints
- attachment presence
- date and recurrence signals
- list, bulk, auto-submitted, and unsubscribe-style headers when exported
- locator provenance and mailbox context

Rules must not require full raw-body duplication.

## Suppression Rules

Suppress low-value mail from extraction by default when it matches:

- newsletter or list headers
- marketing, sale, promo, or unsubscribe-heavy subjects
- repetitive receipts without an explicit reviewed category
- automated alerts, logs, and status notifications
- no-reply or bulk sender patterns with no human follow-up signal

Suppressed messages remain searchable in the metadata index.

## Evaluation Set

The evaluation corpus should include synthetic examples for every lane, plus
edge cases that catch false positives and false negatives. Each case should
record:

- expected lane
- expected confidence band
- matched rule rationale
- whether extraction is allowed
- whether human review is required

Important lanes should have representative positives. Noise should include
newsletters, promotions, receipts, alerts, and repetitive notifications.

## Pass Criteria

Classifier changes should report:

- per-lane pass/fail counts
- changed cases from the previous baseline
- false positive and false negative notes
- explanation coverage for every decision
- raw-body leakage check for logs and reports

The first implementation should prefer conservative `review_needed` decisions
over overconfident promotion into extraction.
