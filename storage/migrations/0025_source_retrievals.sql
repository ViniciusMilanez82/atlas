-- R5-08 (review of PR #5): "registered source", "retrieved source", "consulted in this task" and
-- "supports this claim" are different states. A web source counts as evidence only through a
-- retrieval recorded by an adapter for THIS task (or an explicitly authorized reuse of a retrieval of
-- the same employee), with the canonical/final URL, the captured content (artifact + hash), time,
-- validity and the adapter receipt. A row in ``sources`` alone proves nothing.
CREATE TABLE source_retrievals (
  id              TEXT PRIMARY KEY,
  employee_id     TEXT NOT NULL REFERENCES employees(id),
  task_id         TEXT NOT NULL REFERENCES tasks(id),
  url             TEXT NOT NULL,
  final_url       TEXT NOT NULL,
  artifact_id     TEXT NOT NULL REFERENCES artifacts(id),
  content_sha256  TEXT NOT NULL CHECK (length(content_sha256) = 64),
  adapter         TEXT NOT NULL,
  receipt_json    TEXT NOT NULL,
  retrieved_at    TEXT NOT NULL,
  valid_until     TEXT
) STRICT;
CREATE INDEX idx_source_retrievals_task ON source_retrievals(task_id, url);

-- Reusing an earlier capture in another task of the SAME employee is an explicit, recorded decision.
CREATE TABLE source_uses (
  task_id        TEXT NOT NULL REFERENCES tasks(id),
  retrieval_id   TEXT NOT NULL REFERENCES source_retrievals(id),
  authorized_by  TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  PRIMARY KEY (task_id, retrieval_id)
) STRICT;
