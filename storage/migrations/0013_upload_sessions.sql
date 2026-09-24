-- Contract v2 A3-24 / A3-22: one upload is one durable session shared by every connection. Offsets,
-- quota and expiry are checked inside a write transaction (processes and connections serialize on the
-- database, not on a per-object lock), and the final import is recorded as a receipt: asking again with
-- the same upload_ref returns the artifact already created instead of duplicating it.
CREATE TABLE upload_sessions (
  employee_id     TEXT NOT NULL REFERENCES employees(id),
  upload_ref      TEXT NOT NULL,
  state           TEXT NOT NULL CHECK (state IN ('RECEIVING','IMPORTED','EXPIRED','FAILED')),
  received_bytes  INTEGER NOT NULL DEFAULT 0 CHECK (received_bytes >= 0),
  artifact_id     TEXT REFERENCES artifacts(id),
  failure         TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  expires_at      TEXT NOT NULL,
  PRIMARY KEY (employee_id, upload_ref),
  CHECK ((state = 'IMPORTED') = (artifact_id IS NOT NULL))
) STRICT;
CREATE INDEX idx_upload_sessions_state ON upload_sessions(state, expires_at);
