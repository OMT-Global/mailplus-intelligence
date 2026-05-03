# Index Query Contract

The foundation recall API operates on metadata only. Query results should return
matching messages, thread context, and MailPlus or fixture locators without
requiring raw body duplication.

## Query Inputs

The first contract should support:

- sender email or domain
- recipient email or domain
- subject keyword
- sent date range
- mailbox or folder path
- label or flag
- attachment presence
- thread ID or thread key

Inputs should be composable where practical, for example sender plus date range
or folder plus attachment presence.

## Result Shape

Each result should include:

- message ID
- thread key
- subject
- sent timestamp
- sender and recipients
- mailbox and folder path
- labels and flags
- attachment metadata summary
- locator fields or explicit missing-locator status

Results must not include raw message bodies.

## Error Cases

The query layer should distinguish:

- invalid query input
- no matches
- missing locator
- ambiguous thread
- index schema unavailable

Missing locators should not remove metadata results; they should be visible for
operator review.

## Test Coverage

Offline tests should demonstrate sender, recipient, subject, date range, folder,
label, attachment, and thread lookup against synthetic fixture records.
