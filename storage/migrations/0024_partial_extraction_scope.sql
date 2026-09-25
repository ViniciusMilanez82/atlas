-- R5-06 (review of PR #5): a PARTIAL extraction is not a complete read. The extraction records how
-- many units (pages) the document has and which ones were not extracted; a reduced scope must be
-- accepted explicitly by the owner, per task and document, as an instruction revision.
ALTER TABLE document_extractions ADD COLUMN units_total INTEGER CHECK (units_total IS NULL OR units_total >= 0);
ALTER TABLE document_extractions ADD COLUMN missing_json TEXT NOT NULL DEFAULT '[]';
-- Extractions made before this migration did not record the missing areas: say so, never "none".
UPDATE document_extractions SET missing_json = '["áreas não identificadas (extração anterior à migração 0024)"]'
  WHERE state = 'PARTIAL';

CREATE TABLE input_scope_acceptances (
  task_id               TEXT NOT NULL REFERENCES tasks(id),
  artifact_id           TEXT NOT NULL REFERENCES artifacts(id),
  instruction_revision  INTEGER NOT NULL CHECK (instruction_revision >= 1),
  missing_json          TEXT NOT NULL,
  accepted_by           TEXT NOT NULL,
  note                  TEXT,
  created_at            TEXT NOT NULL,
  PRIMARY KEY (task_id, artifact_id)
) STRICT;
