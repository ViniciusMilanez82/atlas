-- Contract v2: A3-03 (versioned instructions), A3-04 (durable control orders).

-- The owner's request and every later correction/answer, verbatim and versioned. The task points at
-- the revision in force; the broker refuses a proposal decided under an older revision.
CREATE TABLE task_instruction_versions (
  task_id            TEXT NOT NULL REFERENCES tasks(id),
  revision           INTEGER NOT NULL CHECK (revision >= 1),
  kind               TEXT NOT NULL CHECK (kind IN ('ORIGINAL','CORRECTION','ANSWER','ATTACHMENT')),
  instruction        TEXT NOT NULL CHECK (length(instruction) BETWEEN 1 AND 32000),
  material           INTEGER NOT NULL CHECK (material IN (0,1)),
  author             TEXT NOT NULL,
  source_message_id  TEXT REFERENCES messages(id),
  created_at         TEXT NOT NULL,
  PRIMARY KEY (task_id, revision)
) STRICT;

ALTER TABLE tasks ADD COLUMN instruction_revision INTEGER NOT NULL DEFAULT 1 CHECK (instruction_revision >= 1);
ALTER TABLE actions ADD COLUMN instruction_revision INTEGER;

-- Existing tasks: their objective is revision 1 (the full original request was not kept before).
INSERT INTO task_instruction_versions(task_id, revision, kind, instruction, material, author, created_at)
  SELECT id, 1, 'ORIGINAL', objective, 1, 'migration-0008', created_at FROM tasks;

-- Stop/pause/cancel orders are persisted before they are applied, with what they found in flight.
ALTER TABLE employees ADD COLUMN control_epoch INTEGER NOT NULL DEFAULT 0 CHECK (control_epoch >= 0);
CREATE TABLE control_orders (
  id             TEXT PRIMARY KEY,
  employee_id    TEXT NOT NULL REFERENCES employees(id),
  task_id        TEXT REFERENCES tasks(id),
  kind           TEXT NOT NULL CHECK (kind IN ('STOP_ALL','PAUSE','CANCEL')),
  control_epoch  INTEGER NOT NULL CHECK (control_epoch >= 1),
  origin         TEXT NOT NULL,
  requested_at   TEXT NOT NULL,
  applied_at     TEXT,
  report_json    TEXT
) STRICT;
CREATE INDEX idx_control_orders_employee ON control_orders(employee_id, requested_at);
