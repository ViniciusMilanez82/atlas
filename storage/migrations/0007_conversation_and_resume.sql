-- Alpha 2 (review 2a7fd85: A2, A3, A5, A7, A8).

-- Tasks belong to the conversation that created them; client_request_id makes creation idempotent
-- so a client may safely resend after a lost reply or a reconnect.
ALTER TABLE tasks ADD COLUMN conversation_id TEXT REFERENCES conversations(id);
ALTER TABLE tasks ADD COLUMN client_request_id TEXT;
CREATE UNIQUE INDEX idx_tasks_client_request ON tasks(employee_id, client_request_id)
  WHERE client_request_id IS NOT NULL;

-- Both sides of the conversation, typed, with links to artifacts and memory proposals.
ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'
  CHECK (kind IN ('chat','ack','question','answer','status','result','control','memory','correction','error'));
ALTER TABLE messages ADD COLUMN artifact_id TEXT REFERENCES artifacts(id);
ALTER TABLE messages ADD COLUMN memory_id TEXT REFERENCES memories(id);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);

-- Operational result of each step, so an interrupted task resumes from what was observed
-- (never from private reasoning). Tool output stays marked untrusted.
CREATE TABLE step_observations (
  step_id     TEXT PRIMARY KEY REFERENCES steps(id),
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  content     TEXT NOT NULL,
  trust       TEXT NOT NULL CHECK (trust IN ('untrusted','verified')),
  created_at  TEXT NOT NULL
) STRICT;
CREATE INDEX idx_step_obs_task ON step_observations(task_id, created_at);

-- Billable calls outside a task (conversation replies, 'Testar inteligência') use the same ledger.
CREATE TABLE inference_attempts_v2 (
  id              TEXT PRIMARY KEY,
  task_id         TEXT REFERENCES tasks(id),
  employee_id     TEXT REFERENCES employees(id),
  purpose         TEXT NOT NULL DEFAULT 'task' CHECK (purpose IN ('task','conversation','intelligence_check')),
  reservation_id  TEXT NOT NULL REFERENCES budget_reservations(id),
  provider        TEXT NOT NULL,
  model_id        TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('IN_FLIGHT','SETTLED','ESTIMATED','RELEASED','UNKNOWN','RESOLVED')),
  request_id      TEXT,
  diagnostic      TEXT,
  created_at      TEXT NOT NULL,
  closed_at       TEXT,
  CHECK (task_id IS NOT NULL OR employee_id IS NOT NULL)
) STRICT;
INSERT INTO inference_attempts_v2(id, task_id, employee_id, purpose, reservation_id, provider, model_id, status,
  request_id, diagnostic, created_at, closed_at)
  SELECT a.id, a.task_id, t.employee_id, 'task', a.reservation_id, a.provider, a.model_id, a.status, a.request_id,
         a.diagnostic, a.created_at, a.closed_at
  FROM inference_attempts a JOIN tasks t ON t.id = a.task_id;
DROP TABLE inference_attempts;
ALTER TABLE inference_attempts_v2 RENAME TO inference_attempts;
CREATE INDEX idx_inference_attempts_status ON inference_attempts(status, created_at);
