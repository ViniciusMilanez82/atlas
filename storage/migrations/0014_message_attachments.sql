-- Contract v2 A3-15: an attachment belongs to the message that carried it. Keeping, complementing a
-- task and starting a new analysis are different intents; the attachment itself decides none of them.
CREATE TABLE message_attachments (
  message_id   TEXT NOT NULL REFERENCES messages(id),
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  PRIMARY KEY (message_id, artifact_id)
) STRICT;
CREATE INDEX idx_message_attachments_artifact ON message_attachments(artifact_id);
