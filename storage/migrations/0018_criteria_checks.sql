-- Contract v2 A3-07: each completion criterion names the deterministic check that proves it, so one
-- generic "file opens" evidence can no longer satisfy distinct business criteria.
ALTER TABLE task_criteria ADD COLUMN check_kind TEXT
  CHECK (check_kind IS NULL OR check_kind IN ('integrity','coverage','calculations','sources','inputs_read',
                                               'required_terms'));
ALTER TABLE task_criteria ADD COLUMN params_json TEXT;
