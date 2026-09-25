-- N14 (mediation part): every outbound web request on behalf of a task leaves a receipt, allowed or
-- refused, with the address it was pinned to and what came back. The URL is stored redacted.
CREATE TABLE network_requests (
  id           TEXT PRIMARY KEY,
  task_id      TEXT REFERENCES tasks(id),
  purpose      TEXT NOT NULL,
  url          TEXT NOT NULL,
  resolved_ip  TEXT,
  decision     TEXT NOT NULL CHECK (decision IN ('ALLOWED','REFUSED','REDIRECT','FAILED')),
  reason       TEXT NOT NULL,
  status       INTEGER,
  bytes        INTEGER NOT NULL DEFAULT 0 CHECK (bytes >= 0),
  sha256       TEXT,
  created_at   TEXT NOT NULL
) STRICT;
CREATE INDEX idx_network_requests_task ON network_requests(task_id, created_at);
