-- Canonical semantic provenance, append-only review history, and export outbox
-- (issue #102). Migration 003 is intentionally left untouched so existing
-- databases receive a deterministic legacy backfill.

BEGIN IMMEDIATE;

ALTER TABLE promotion_queue RENAME TO promotion_queue_v3;

CREATE TABLE promotion_queue (
  id INTEGER PRIMARY KEY,
  artifact_id TEXT NOT NULL UNIQUE,
  artifact_type TEXT NOT NULL CHECK (
    artifact_type IN ('thread_summary', 'entity_update', 'obligation', 'decision', 'event')
  ),
  source_message_ids TEXT NOT NULL CHECK (
    json_valid(source_message_ids) AND json_type(source_message_ids) = 'array'
  ),
  source_locators TEXT NOT NULL CHECK (
    json_valid(source_locators) AND json_type(source_locators) = 'array'
  ),
  evidence_refs TEXT NOT NULL CHECK (
    json_valid(evidence_refs) AND json_type(evidence_refs) = 'array'
  ),
  source_thread_key TEXT NOT NULL,
  summary TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
  provenance TEXT NOT NULL CHECK (provenance IN ('deterministic', 'llm', 'legacy')),
  extractor_version TEXT NOT NULL,
  model_version TEXT,
  rule_version TEXT,
  artifact_created_at TEXT NOT NULL,
  initial_review_status TEXT NOT NULL CHECK (
    initial_review_status IN ('candidate', 'review_needed')
  ),
  review_status TEXT NOT NULL CHECK (
    review_status IN (
      'candidate', 'review_needed', 'approved', 'rejected', 'deferred',
      'corrected', 'rollback_needed'
    )
  ),
  revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
  latest_review_event_id TEXT,
  reviewer_identity TEXT,
  reviewer_notes TEXT,
  corrected_summary TEXT,
  queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_at TEXT
);

INSERT INTO promotion_queue (
  id,
  artifact_id,
  artifact_type,
  source_message_ids,
  source_locators,
  evidence_refs,
  source_thread_key,
  summary,
  confidence,
  provenance,
  extractor_version,
  model_version,
  rule_version,
  artifact_created_at,
  initial_review_status,
  review_status,
  revision,
  latest_review_event_id,
  reviewer_identity,
  reviewer_notes,
  corrected_summary,
  queued_at,
  decided_at
)
SELECT
  id,
  artifact_id,
  artifact_type,
  '[]',
  CASE
    WHEN json_valid(source_locators) AND json_type(source_locators) = 'array'
      THEN source_locators
    ELSE '[]'
  END,
  CASE
    WHEN json_valid(provenance) AND json_type(provenance) = 'array'
      THEN provenance
    ELSE '[]'
  END,
  source_thread_key,
  summary,
  confidence,
  'legacy',
  'legacy-unknown',
  NULL,
  NULL,
  queued_at,
  CASE
    WHEN review_status = 'review_needed' THEN 'review_needed'
    ELSE 'candidate'
  END,
  review_status,
  CASE
    WHEN review_status IN ('candidate', 'review_needed') THEN 0
    ELSE 1
  END,
  CASE
    WHEN review_status IN ('candidate', 'review_needed') THEN NULL
    ELSE 'legacy-review-' || artifact_id || '-1'
  END,
  CASE
    WHEN review_status IN ('candidate', 'review_needed') THEN NULL
    ELSE 'legacy-migration'
  END,
  reviewer_notes,
  corrected_summary,
  queued_at,
  decided_at
FROM promotion_queue_v3;

DROP TABLE promotion_queue_v3;

CREATE INDEX idx_promotion_queue_status ON promotion_queue(review_status);
CREATE INDEX idx_promotion_queue_artifact_type ON promotion_queue(artifact_type);

CREATE TABLE review_events (
  id INTEGER PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE,
  artifact_id TEXT NOT NULL REFERENCES promotion_queue(artifact_id) ON DELETE RESTRICT,
  artifact_revision INTEGER NOT NULL CHECK (artifact_revision > 0),
  event_type TEXT NOT NULL CHECK (event_type IN ('review.decision', 'review.legacy_backfill')),
  prior_status TEXT NOT NULL CHECK (
    prior_status IN (
      'candidate', 'review_needed', 'approved', 'rejected', 'deferred',
      'corrected', 'rollback_needed'
    )
  ),
  new_status TEXT NOT NULL CHECK (
    new_status IN (
      'candidate', 'review_needed', 'approved', 'rejected', 'deferred',
      'corrected', 'rollback_needed'
    )
  ),
  reviewer_identity TEXT NOT NULL,
  reviewer_notes TEXT,
  corrected_summary TEXT,
  occurred_at TEXT NOT NULL,
  UNIQUE (artifact_id, artifact_revision)
);

INSERT INTO review_events (
  event_id,
  artifact_id,
  artifact_revision,
  event_type,
  prior_status,
  new_status,
  reviewer_identity,
  reviewer_notes,
  corrected_summary,
  occurred_at
)
SELECT
  latest_review_event_id,
  artifact_id,
  revision,
  'review.legacy_backfill',
  initial_review_status,
  review_status,
  'legacy-migration',
  reviewer_notes,
  corrected_summary,
  COALESCE(decided_at, queued_at)
FROM promotion_queue
WHERE latest_review_event_id IS NOT NULL;

CREATE INDEX idx_review_events_artifact_revision
  ON review_events(artifact_id, artifact_revision);
CREATE INDEX idx_review_events_occurred_at ON review_events(occurred_at);

CREATE TABLE export_outbox (
  id INTEGER PRIMARY KEY,
  outbox_id TEXT NOT NULL UNIQUE,
  artifact_id TEXT NOT NULL REFERENCES promotion_queue(artifact_id) ON DELETE RESTRICT,
  artifact_revision INTEGER NOT NULL CHECK (artifact_revision > 0),
  review_event_id TEXT NOT NULL REFERENCES review_events(event_id) ON DELETE RESTRICT,
  export_type TEXT NOT NULL,
  target_key TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  content_hash TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'planned' CHECK (
    state IN ('planned', 'exported', 'failed', 'rollback_needed', 'rolled_back')
  ),
  target_metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(target_metadata)),
  rollback_note TEXT,
  failure_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  exported_at TEXT,
  rollback_requested_at TEXT,
  rolled_back_at TEXT,
  UNIQUE (artifact_id, artifact_revision, export_type, target_key)
);

CREATE INDEX idx_export_outbox_artifact ON export_outbox(artifact_id, artifact_revision);
CREATE INDEX idx_export_outbox_state ON export_outbox(state);

CREATE TRIGGER promotion_queue_immutable_envelope
BEFORE UPDATE OF
  artifact_id,
  artifact_type,
  source_message_ids,
  source_locators,
  evidence_refs,
  source_thread_key,
  summary,
  confidence,
  provenance,
  extractor_version,
  model_version,
  rule_version,
  artifact_created_at,
  initial_review_status
ON promotion_queue
BEGIN
  SELECT RAISE(ABORT, 'semantic artifact envelope is immutable');
END;

CREATE TRIGGER promotion_queue_immutable_delete
BEFORE DELETE ON promotion_queue
BEGIN
  SELECT RAISE(ABORT, 'semantic artifacts cannot be deleted');
END;

CREATE TRIGGER review_events_append_only_update
BEFORE UPDATE ON review_events
BEGIN
  SELECT RAISE(ABORT, 'review events are append-only');
END;

CREATE TRIGGER review_events_append_only_delete
BEFORE DELETE ON review_events
BEGIN
  SELECT RAISE(ABORT, 'review events are append-only');
END;

CREATE TRIGGER promotion_queue_review_snapshot_consistent
BEFORE UPDATE OF
  review_status,
  revision,
  latest_review_event_id,
  reviewer_identity,
  reviewer_notes,
  corrected_summary,
  decided_at
ON promotion_queue
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1
    FROM review_events
    WHERE event_id = NEW.latest_review_event_id
      AND artifact_id = NEW.artifact_id
      AND artifact_revision = NEW.revision
      AND new_status = NEW.review_status
      AND reviewer_identity = NEW.reviewer_identity
      AND reviewer_notes IS NEW.reviewer_notes
      AND corrected_summary IS NEW.corrected_summary
      AND occurred_at = NEW.decided_at
  ) THEN RAISE(ABORT, 'queue review snapshot must match its append-only event') END;
END;

PRAGMA user_version = 4;

COMMIT;
