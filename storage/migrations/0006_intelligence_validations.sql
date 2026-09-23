-- Results of the owner-authorized "Testar inteligência" (spec 7.3). A model becomes usable only
-- after a passing row for its exact id; catalog presence is not access.
CREATE TABLE intelligence_validations (
  id           TEXT PRIMARY KEY,
  provider     TEXT NOT NULL,
  model_id     TEXT NOT NULL,
  passed       INTEGER NOT NULL CHECK (passed IN (0,1)),
  report_json  TEXT NOT NULL,
  cost_minor   INTEGER,
  currency     TEXT,
  checked_at   TEXT NOT NULL,
  checked_by   TEXT NOT NULL
) STRICT;
CREATE INDEX idx_intel_model ON intelligence_validations(provider, model_id, checked_at);
