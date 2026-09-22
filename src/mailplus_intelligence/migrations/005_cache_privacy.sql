-- Selected-text disposal metadata and model-egress audit controls (issue #103).

BEGIN IMMEDIATE;

ALTER TABLE text_cache ADD COLUMN purpose TEXT NOT NULL DEFAULT 'legacy-migration'
  CHECK (purpose IN ('extraction', 'review', 'fixture-repro', 'legacy-migration'));
ALTER TABLE text_cache ADD COLUMN redaction_state TEXT NOT NULL DEFAULT 'legacy-unknown'
  CHECK (redaction_state IN ('unreviewed', 'redacted', 'minimal', 'synthetic', 'legacy-unknown'));
ALTER TABLE text_cache ADD COLUMN provenance TEXT NOT NULL DEFAULT 'legacy'
  CHECK (provenance IN ('operator-selected', 'mailplus-fetch', 'fixture', 'legacy'));
ALTER TABLE text_cache ADD COLUMN review_required INTEGER NOT NULL DEFAULT 1
  CHECK (review_required IN (0, 1));
ALTER TABLE text_cache ADD COLUMN disposed_at TEXT;

CREATE TABLE IF NOT EXISTS text_cache_events (
  id INTEGER PRIMARY KEY,
  locator_ref TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message_class TEXT,
  detail_code TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_text_cache_events_locator
  ON text_cache_events(locator_ref, created_at);

-- Record the migration-driven lifecycle before overwriting legacy text. No
-- selected text or content hash is copied into the event stream.
INSERT INTO text_cache_events (
  locator_ref, event_type, message_class, detail_code
)
SELECT 'legacy-row:' || id, 'cache_expiry', message_class, 'legacy-migration'
FROM text_cache
WHERE julianday(expires_at) <= julianday('now');

INSERT INTO text_cache_events (
  locator_ref, event_type, message_class, detail_code
)
SELECT 'legacy-row:' || id, 'cache_disposal', message_class, 'text-overwritten'
FROM text_cache
WHERE evicted_at IS NOT NULL OR julianday(expires_at) <= julianday('now');

-- Entries already evicted or expired must not retain selected text. The row
-- remains as a privacy-safe lifecycle tombstone.
UPDATE text_cache
SET cached_text = '',
    evicted_at = COALESCE(evicted_at, CURRENT_TIMESTAMP),
    disposed_at = COALESCE(evicted_at, CURRENT_TIMESTAMP)
WHERE evicted_at IS NOT NULL OR julianday(expires_at) <= julianday('now');

CREATE TRIGGER text_cache_disposed_insert_guard
BEFORE INSERT ON text_cache
WHEN (NEW.evicted_at IS NOT NULL OR NEW.disposed_at IS NOT NULL) AND NEW.cached_text <> ''
BEGIN
  SELECT RAISE(ABORT, 'disposed cache rows cannot retain cached_text');
END;

CREATE TRIGGER text_cache_disposed_update_guard
BEFORE UPDATE OF cached_text, evicted_at, disposed_at ON text_cache
WHEN (NEW.evicted_at IS NOT NULL OR NEW.disposed_at IS NOT NULL) AND NEW.cached_text <> ''
BEGIN
  SELECT RAISE(ABORT, 'disposed cache rows cannot retain cached_text');
END;

CREATE TABLE IF NOT EXISTS llm_egress_events (
  id INTEGER PRIMARY KEY,
  request_id TEXT NOT NULL,
  thread_ref_hash TEXT NOT NULL,
  provider_mode TEXT NOT NULL CHECK (provider_mode IN ('local', 'cloud')),
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  data_classes TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('authorized', 'completed', 'failed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (request_id, status)
);

CREATE INDEX IF NOT EXISTS idx_llm_egress_events_created_at
  ON llm_egress_events(created_at);

PRAGMA user_version = 5;

COMMIT;
