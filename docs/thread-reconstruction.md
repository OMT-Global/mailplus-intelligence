# Thread Reconstruction Rules

Fixture thread reconstruction uses deterministic evidence in this order:

1. exact duplicate `message_id` records
2. `references` links to known message IDs
3. `in_reply_to` links to known message IDs
4. conservative normalized-subject fallback for reply/forward prefixes

Malformed optional headers do not block indexing, but they lower confidence and
are surfaced for review. Subject fallback is medium confidence because repeated
subjects can be unrelated. Exact header links and duplicate source IDs are high
confidence when locators remain distinct.

Live MailPlus threading remains a future source-specific override. Fixture
threading must stay deterministic so regression tests can explain every grouped
message.
