-- Declarative table skills are a separate type, not executable packages or broader permissions.
CREATE TABLE table_skill_versions (
  id TEXT PRIMARY KEY,
  employee_id TEXT NOT NULL REFERENCES employees(id),
  skill_key TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version > 0),
  description TEXT NOT NULL,
  definition_json TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  classification TEXT NOT NULL CHECK(classification IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE')),
  source_task_id TEXT REFERENCES tasks(id),
  state TEXT NOT NULL CHECK(state IN ('DRAFT','TESTED','ACTIVE','SUPERSEDED','QUARANTINED','REVOKED')),
  revision INTEGER NOT NULL DEFAULT 1,
  approved_engine TEXT,
  approved_by TEXT,
  failure_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(employee_id,skill_key,version)
) STRICT;
CREATE UNIQUE INDEX table_skill_one_active ON table_skill_versions(employee_id,skill_key) WHERE state = 'ACTIVE';
CREATE TABLE table_skill_tests (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES table_skill_versions(id),
 content_hash TEXT NOT NULL, engine_hash TEXT NOT NULL, passed INTEGER NOT NULL CHECK(passed IN (0,1)),
 report_json TEXT NOT NULL, created_at TEXT NOT NULL
) STRICT;
CREATE TABLE table_skill_uses (
 action_id TEXT PRIMARY KEY REFERENCES actions(id), version_id TEXT NOT NULL REFERENCES table_skill_versions(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), input_hash TEXT NOT NULL,
 output_hash TEXT, error_code TEXT, created_at TEXT NOT NULL,
 CHECK((output_hash IS NULL) != (error_code IS NULL))
) STRICT;
CREATE TABLE table_skill_receipts (
 employee_id TEXT NOT NULL REFERENCES employees(id), request_id TEXT NOT NULL,
 request_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(employee_id,request_id)
) STRICT;
CREATE TRIGGER table_skill_definition_immutable BEFORE UPDATE OF
 employee_id,skill_key,version,description,definition_json,content_hash,classification,source_task_id ON table_skill_versions
BEGIN SELECT RAISE(ABORT,'skill version content is immutable; propose another version'); END;
CREATE TRIGGER table_skill_test_immutable BEFORE UPDATE ON table_skill_tests
BEGIN SELECT RAISE(ABORT,'skill test evidence is immutable'); END;
CREATE TRIGGER table_skill_use_immutable BEFORE UPDATE ON table_skill_uses
BEGIN SELECT RAISE(ABORT,'skill use evidence is immutable'); END;
