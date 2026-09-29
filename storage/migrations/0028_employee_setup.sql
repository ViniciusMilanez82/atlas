-- N22: durable first-use acknowledgement; not a flag granting any runtime permission.
CREATE TABLE employee_setup (
  employee_id TEXT PRIMARY KEY REFERENCES employees(id),
  completed_at TEXT NOT NULL,
  profile_version INTEGER NOT NULL CHECK (profile_version > 0),
  settings_revision INTEGER NOT NULL CHECK (settings_revision > 0),
  mode TEXT NOT NULL CHECK (mode IN ('limited', 'ready'))
) STRICT;
