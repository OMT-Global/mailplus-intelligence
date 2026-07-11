BEGIN;

CREATE TABLE ingest_decisions (
  locator_export_id TEXT PRIMARY KEY REFERENCES messages(locator_export_id) ON DELETE RESTRICT,
  thread_key TEXT NOT NULL,
  lane TEXT NOT NULL,
  thread_confidence TEXT NOT NULL CHECK (thread_confidence IN ('high', 'medium', 'low', 'review-needed')),
  suppression_action TEXT NOT NULL CHECK (suppression_action IN ('allow', 'suppress', 'review_needed')),
  extraction_eligible INTEGER NOT NULL CHECK (extraction_eligible IN (0, 1)),
  reason_codes TEXT NOT NULL,
  source_state TEXT NOT NULL DEFAULT 'present' CHECK (source_state IN ('present', 'missing', 'deleted')),
  decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  missing_at TEXT
);

CREATE INDEX idx_ingest_decisions_thread_key ON ingest_decisions(thread_key);
CREATE INDEX idx_ingest_decisions_eligibility ON ingest_decisions(extraction_eligible, source_state);

CREATE TABLE message_locator_history (
  id INTEGER PRIMARY KEY,
  locator_export_id TEXT NOT NULL REFERENCES messages(locator_export_id) ON DELETE RESTRICT,
  account TEXT NOT NULL,
  mailbox TEXT NOT NULL,
  folder_path TEXT NOT NULL,
  locator_uid TEXT NOT NULL,
  source_state TEXT NOT NULL CHECK (source_state IN ('present', 'missing', 'deleted')),
  observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(locator_export_id, account, mailbox, folder_path, locator_uid, source_state)
);

CREATE INDEX idx_message_locator_history_export_id ON message_locator_history(locator_export_id, observed_at);

PRAGMA user_version = 6;
COMMIT;
