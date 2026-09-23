-- Attempt limits (spec 9.4) and scheduled-job occurrences (spec 9.3).
CREATE TABLE task_progress (
  task_id                     TEXT PRIMARY KEY REFERENCES tasks(id),
  transient_failures          INTEGER NOT NULL DEFAULT 0 CHECK (transient_failures >= 0),
  replans_without_progress    INTEGER NOT NULL DEFAULT 0 CHECK (replans_without_progress >= 0),
  steps_without_verified      INTEGER NOT NULL DEFAULT 0 CHECK (steps_without_verified >= 0),
  next_attempt_at             TEXT,
  updated_at                  TEXT NOT NULL
) STRICT;

-- Daily jobs anchored to a local wall-clock time (DST-aware); NULL means fixed interval.
ALTER TABLE scheduled_jobs ADD COLUMN local_time TEXT
  CHECK (local_time IS NULL OR local_time GLOB '[0-2][0-9]:[0-5][0-9]');
ALTER TABLE scheduled_jobs ADD COLUMN owner_id TEXT REFERENCES owners(id);

CREATE TABLE job_runs (
  job_id         TEXT NOT NULL REFERENCES scheduled_jobs(id),
  occurrence_at  TEXT NOT NULL,
  task_id        TEXT REFERENCES tasks(id),
  missed_count   INTEGER NOT NULL DEFAULT 0 CHECK (missed_count >= 0),
  created_at     TEXT NOT NULL,
  PRIMARY KEY (job_id, occurrence_at)
) STRICT;
