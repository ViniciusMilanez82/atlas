-- Every billable model call is recorded BEFORE it is sent (review finding R-04, spec 7.4).
-- IN_FLIGHT   intent persisted with its budget reservation, request not yet resolved
-- SETTLED     consumption confirmed by provider-reported usage
-- ESTIMATED   response received without usage: settled at the reserved maximum, still reconcilable
-- RELEASED    proven not sent / not billed: reservation released
-- UNKNOWN     sending or billing is uncertain: reservation held until reconciliation or retention expiry
-- RESOLVED    an UNKNOWN or ESTIMATED attempt later reconciled with evidence
CREATE TABLE inference_attempts (
  id              TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  reservation_id  TEXT NOT NULL REFERENCES budget_reservations(id),
  provider        TEXT NOT NULL,
  model_id        TEXT NOT NULL,
  status          TEXT NOT NULL CHECK (status IN ('IN_FLIGHT','SETTLED','ESTIMATED','RELEASED','UNKNOWN','RESOLVED')),
  request_id      TEXT,
  diagnostic      TEXT,
  created_at      TEXT NOT NULL,
  closed_at       TEXT
) STRICT;
CREATE INDEX idx_inference_attempts_status ON inference_attempts(status, created_at);
