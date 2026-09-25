-- R5-02 (review of PR #5): the ORIGINAL instruction is the authenticated owner message, verbatim, with
-- a content hash recorded at publication. Legacy revisions keep NULL (their hash was never recorded;
-- nothing is invented for them).
ALTER TABLE task_instruction_versions ADD COLUMN content_sha256 TEXT
  CHECK (content_sha256 IS NULL OR length(content_sha256) = 64);

-- Criteria gain the 'condition' check (one per condition of the request, with its source passage) and
-- 'substance' (the deliverable does the work instead of denying it, R5-05). They also record the
-- instruction revision they were derived for (R5-04). SQLite cannot widen a CHECK in place: the table
-- is rebuilt with every row and its rowid order (criteria are listed by rowid).
CREATE TABLE task_criteria_new (
  id                  TEXT PRIMARY KEY,
  task_id             TEXT NOT NULL REFERENCES tasks(id),
  description         TEXT NOT NULL,
  required            INTEGER NOT NULL CHECK (required IN (0,1)),
  satisfied_at        TEXT,
  evidence_id         TEXT REFERENCES evidence(id),
  check_kind          TEXT CHECK (check_kind IS NULL OR check_kind IN ('integrity','coverage','calculations',
                        'sources','inputs_read','required_terms','condition','substance')),
  params_json         TEXT,
  instruction_revision INTEGER NOT NULL DEFAULT 1 CHECK (instruction_revision >= 1)
) STRICT;
INSERT INTO task_criteria_new(rowid, id, task_id, description, required, satisfied_at, evidence_id, check_kind,
                              params_json)
  SELECT rowid, id, task_id, description, required, satisfied_at, evidence_id, check_kind, params_json
  FROM task_criteria ORDER BY rowid;
DROP TABLE task_criteria;
ALTER TABLE task_criteria_new RENAME TO task_criteria;
CREATE INDEX idx_task_criteria_task ON task_criteria(task_id);
