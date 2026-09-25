-- Contract v2: A3-11 (durable request receipts) and A3-27 (transactional notification outbox).

-- One row per (employee, operation, client key). The payload hash is immutable: the same key with a
-- different payload is a conflict. PROCESSING carries a lease so a crashed processor can be resumed.
CREATE TABLE request_receipts (
  employee_id       TEXT NOT NULL REFERENCES employees(id),
  operation         TEXT NOT NULL CHECK (operation IN ('conversations.send','artifacts.import')),
  request_key       TEXT NOT NULL,
  payload_hash      TEXT NOT NULL,
  state             TEXT NOT NULL CHECK (state IN ('RECEIVED','PROCESSING','COMPLETED','FAILED',
                      'RECONCILIATION_REQUIRED')),
  message_id        TEXT REFERENCES messages(id),
  decision_json     TEXT,
  result_json       TEXT,
  lease_expires_at  TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (employee_id, operation, request_key),
  CHECK ((state = 'PROCESSING') = (lease_expires_at IS NOT NULL))
) STRICT;

-- Messages already processed before this migration are complete by definition (legacy hash).
INSERT INTO request_receipts(employee_id, operation, request_key, payload_hash, state, message_id, result_json,
  created_at, updated_at)
  SELECT c.employee_id, 'conversations.send', m.client_message_id, 'legacy', 'COMPLETED', m.id,
         json_object('intent', 'legacy', 'task_id', m.task_id,
                     'reply_id', (SELECT r.id FROM messages r WHERE r.conversation_id = m.conversation_id
                                  AND r.client_message_id = 'reply:' || m.id)),
         m.created_at, m.created_at
  FROM messages m JOIN conversations c ON c.id = m.conversation_id
  WHERE m.role = 'owner' AND m.client_message_id IS NOT NULL;

-- A question, result or status for the owner is written in the SAME transaction as the task state
-- change that produced it; a dispatcher delivers it and records the delivery exactly once locally.
CREATE TABLE notification_outbox (
  event_id      TEXT PRIMARY KEY,
  employee_id   TEXT NOT NULL REFERENCES employees(id),
  task_id       TEXT REFERENCES tasks(id),
  channel       TEXT NOT NULL CHECK (channel IN ('conversation')),
  kind          TEXT NOT NULL CHECK (kind IN ('question','result','status','error')),
  content       TEXT NOT NULL,
  artifact_id   TEXT REFERENCES artifacts(id),
  status        TEXT NOT NULL CHECK (status IN ('PENDING','DELIVERED','FAILED')),
  attempts      INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  message_id    TEXT REFERENCES messages(id),
  last_error    TEXT,
  created_at    TEXT NOT NULL,
  delivered_at  TEXT,
  CHECK ((status = 'DELIVERED') = (message_id IS NOT NULL))
) STRICT;
CREATE INDEX idx_outbox_pending ON notification_outbox(status, created_at);
