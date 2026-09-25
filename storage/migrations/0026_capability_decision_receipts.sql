-- R5-09 (review of PR #5): a capability decision, the instruction it creates, the task's return to the
-- queue and the owner notice commit together; the decision keeps a hash of its content so resending
-- the same decision returns the same result and a different one is a conflict. Requests can also end
-- EXPIRED (quote too old), SUPERSEDED (new conditions filed) or CANCELLED (task ended). Rebuilt to widen
-- the status CHECK; every row is kept.
CREATE TABLE capability_requests_new (
  id                 TEXT PRIMARY KEY,
  task_id            TEXT NOT NULL REFERENCES tasks(id),
  employee_id        TEXT NOT NULL REFERENCES employees(id),
  request_json       TEXT NOT NULL,
  status             TEXT NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED','SUPERSEDED',
                       'CANCELLED')),
  created_at         TEXT NOT NULL,
  decided_at         TEXT,
  decided_by         TEXT,
  note               TEXT,
  request_sha256     TEXT,
  decision_sha256    TEXT,
  decision_revision  INTEGER
) STRICT;
INSERT INTO capability_requests_new(rowid, id, task_id, employee_id, request_json, status, created_at, decided_at,
                                    decided_by, note)
  SELECT rowid, id, task_id, employee_id, request_json, status, created_at, decided_at, decided_by, note
  FROM capability_requests ORDER BY rowid;
DROP TABLE capability_requests;
ALTER TABLE capability_requests_new RENAME TO capability_requests;
CREATE INDEX idx_capability_requests_employee ON capability_requests(employee_id, status);
-- Decisions taken before this migration have no recorded instruction: a replay of the same decision
-- completes the missing local steps (decision_revision stays NULL until then).
