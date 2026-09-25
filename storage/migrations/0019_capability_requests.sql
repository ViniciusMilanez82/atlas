-- Contract v2 N18: concrete requests for a missing capability, decided by the owner. Approval is recorded
-- as a decision only; it neither buys anything nor widens what data may leave (Egress Guard).
CREATE TABLE capability_requests (
  id            TEXT PRIMARY KEY,
  task_id       TEXT NOT NULL REFERENCES tasks(id),
  employee_id   TEXT NOT NULL REFERENCES employees(id),
  request_json  TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED')),
  created_at    TEXT NOT NULL,
  decided_at    TEXT,
  decided_by    TEXT,
  note          TEXT
) STRICT;
CREATE INDEX idx_capability_requests_employee ON capability_requests(employee_id, status);
