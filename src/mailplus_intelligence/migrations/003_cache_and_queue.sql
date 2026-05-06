-- Selected-text cache store (issue #69) and promotion review queue (issue #35).

CREATE TABLE IF NOT EXISTS text_cache (
  id INTEGER PRIMARY KEY,
  locator_export_id TEXT NOT NULL UNIQUE,
  message_class TEXT NOT NULL,
  cached_text TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT NOT NULL,
  evicted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_text_cache_expires_at ON text_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_text_cache_message_class ON text_cache(message_class);

CREATE TABLE IF NOT EXISTS promotion_queue (
  id INTEGER PRIMARY KEY,
  artifact_id TEXT NOT NULL UNIQUE,
  artifact_type TEXT NOT NULL CHECK (
    artifact_type IN ('thread_summary', 'entity_update', 'obligation', 'decision', 'event')
  ),
  source_locators TEXT NOT NULL,
  source_thread_key TEXT NOT NULL,
  summary TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  provenance TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'candidate' CHECK (
    review_status IN ('candidate', 'review_needed', 'approved', 'rejected', 'deferred', 'corrected', 'rollback_needed')
  ),
  reviewer_notes TEXT,
  corrected_summary TEXT,
  queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_promotion_queue_status ON promotion_queue(review_status);
CREATE INDEX IF NOT EXISTS idx_promotion_queue_artifact_type ON promotion_queue(artifact_type);

PRAGMA user_version = 3;
