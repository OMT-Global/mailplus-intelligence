-- Extend attachments table with content_id and inline_flag columns.
-- Existing rows default to no content-id and non-inline.
ALTER TABLE attachments ADD COLUMN content_id TEXT;
ALTER TABLE attachments ADD COLUMN inline_flag INTEGER NOT NULL DEFAULT 0
  CHECK (inline_flag IN (0, 1));

CREATE INDEX IF NOT EXISTS idx_attachments_content_type ON attachments(content_type);
CREATE INDEX IF NOT EXISTS idx_attachments_filename ON attachments(filename);

PRAGMA user_version = 2;
