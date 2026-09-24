-- Contract v2 A3-23: the app reconciles its history by a stable order (rowid 'sequence') and by a
-- global, monotonic change counter: a message whose kind or task link changes later gets a new
-- 'revision', so a client that already shows it can upsert the new version instead of ignoring it.
CREATE TABLE message_changes (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id  TEXT NOT NULL REFERENCES messages(id)
) STRICT;
CREATE INDEX idx_message_changes_message ON message_changes(message_id, seq);
INSERT INTO message_changes(message_id) SELECT id FROM messages ORDER BY rowid;
CREATE TRIGGER messages_changed_insert AFTER INSERT ON messages
BEGIN
  INSERT INTO message_changes(message_id) VALUES (NEW.id);
END;
CREATE TRIGGER messages_changed_update AFTER UPDATE OF kind, task_id, content, classification, artifact_id,
  memory_id ON messages
BEGIN
  INSERT INTO message_changes(message_id) VALUES (NEW.id);
END;
