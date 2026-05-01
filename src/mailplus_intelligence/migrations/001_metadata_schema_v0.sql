PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mailboxes (
  id INTEGER PRIMARY KEY,
  account TEXT NOT NULL,
  mailbox TEXT NOT NULL,
  folder_path TEXT NOT NULL,
  UNIQUE (account, mailbox, folder_path)
);

CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY,
  thread_key TEXT NOT NULL UNIQUE,
  subject_normalized TEXT NOT NULL,
  confidence TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low', 'review-needed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  message_id TEXT NOT NULL,
  thread_id INTEGER REFERENCES threads(id) ON DELETE SET NULL,
  mailbox_id INTEGER NOT NULL REFERENCES mailboxes(id) ON DELETE RESTRICT,
  subject TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  has_attachments INTEGER NOT NULL DEFAULT 0 CHECK (has_attachments IN (0, 1)),
  locator_export_id TEXT NOT NULL,
  locator_uid TEXT NOT NULL,
  raw_body_cached INTEGER NOT NULL DEFAULT 0 CHECK (raw_body_cached IN (0, 1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (mailbox_id, locator_uid),
  UNIQUE (locator_export_id)
);

CREATE TABLE IF NOT EXISTS participants (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT
);

CREATE TABLE IF NOT EXISTS message_participants (
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE RESTRICT,
  role TEXT NOT NULL CHECK (role IN ('from', 'to', 'cc', 'bcc')),
  PRIMARY KEY (message_id, participant_id, role)
);

CREATE TABLE IF NOT EXISTS labels (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS message_labels (
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE RESTRICT,
  PRIMARY KEY (message_id, label_id)
);

CREATE TABLE IF NOT EXISTS flags (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS message_flags (
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  flag_id INTEGER NOT NULL REFERENCES flags(id) ON DELETE RESTRICT,
  PRIMARY KEY (message_id, flag_id)
);

CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0)
);

CREATE TABLE IF NOT EXISTS message_relationships (
  id INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  related_message_id TEXT NOT NULL,
  relationship TEXT NOT NULL CHECK (relationship IN ('references', 'in-reply-to')),
  UNIQUE (message_id, related_message_id, relationship)
);

CREATE TABLE IF NOT EXISTS sync_checkpoints (
  id INTEGER PRIMARY KEY,
  source_name TEXT NOT NULL UNIQUE,
  cursor TEXT NOT NULL,
  last_success_at TEXT,
  last_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at);
CREATE INDEX IF NOT EXISTS idx_messages_subject ON messages(subject);
CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_mailbox_id ON messages(mailbox_id);
CREATE INDEX IF NOT EXISTS idx_participants_email ON participants(email);
CREATE INDEX IF NOT EXISTS idx_message_participants_role ON message_participants(role);
CREATE INDEX IF NOT EXISTS idx_attachments_message_id ON attachments(message_id);

PRAGMA user_version = 1;
