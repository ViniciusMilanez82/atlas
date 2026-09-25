-- R5-04 (review of PR #5): evidence declares the instruction revision it evaluated, and criteria that a
-- later material instruction replaced are kept (history) but marked superseded. COMPLETED requires
-- every live required criterion to be satisfied by evidence of the revision in force.
ALTER TABLE evidence ADD COLUMN instruction_revision INTEGER CHECK (instruction_revision IS NULL OR instruction_revision >= 1);
ALTER TABLE task_criteria ADD COLUMN superseded_revision INTEGER
  CHECK (superseded_revision IS NULL OR superseded_revision >= 2);
-- Evidence written before this migration does not say which revision it evaluated: it cannot prove
-- the current one. Open tasks must verify again (nothing already COMPLETED is touched).
UPDATE task_criteria SET satisfied_at = NULL, evidence_id = NULL
  WHERE satisfied_at IS NOT NULL
    AND task_id IN (SELECT id FROM tasks WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED'));
