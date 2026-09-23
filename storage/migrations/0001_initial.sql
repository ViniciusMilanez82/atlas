-- Atlas initial relational model (spec 13.2). Instants are UTC text with Z suffix.
-- Money is integer minor units + ISO 4217 currency. Enums are closed via CHECK.

CREATE TABLE owners (
  id            TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  created_at    TEXT NOT NULL
) STRICT;

CREATE TABLE employees (
  id               TEXT PRIMARY KEY,
  owner_id         TEXT NOT NULL REFERENCES owners(id),
  name             TEXT NOT NULL,
  locale           TEXT NOT NULL,
  timezone         TEXT NOT NULL,
  profile_version  INTEGER NOT NULL DEFAULT 1 CHECK (profile_version >= 1),
  created_at       TEXT NOT NULL
) STRICT;

CREATE TABLE devices (
  id          TEXT PRIMARY KEY,
  owner_id    TEXT NOT NULL REFERENCES owners(id),
  name        TEXT NOT NULL,
  public_key  TEXT NOT NULL,
  paired_at   TEXT NOT NULL,
  revoked_at  TEXT
) STRICT;

CREATE TABLE conversations (
  id           TEXT PRIMARY KEY,
  employee_id  TEXT NOT NULL REFERENCES employees(id),
  created_at   TEXT NOT NULL
) STRICT;

CREATE TABLE tasks (
  id                   TEXT PRIMARY KEY,
  owner_id             TEXT NOT NULL REFERENCES owners(id),
  employee_id          TEXT NOT NULL REFERENCES employees(id),
  objective            TEXT NOT NULL CHECK (length(objective) BETWEEN 1 AND 4000),
  constraints_json     TEXT NOT NULL,
  priority             TEXT NOT NULL CHECK (priority IN ('LOW','NORMAL','HIGH','URGENT')),
  data_policy          TEXT NOT NULL CHECK (data_policy IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET')),
  budget_amount_minor  INTEGER CHECK (budget_amount_minor IS NULL OR budget_amount_minor >= 0),
  budget_currency      TEXT,
  state                TEXT NOT NULL CHECK (state IN ('CREATED','UNDERSTANDING','PLANNING','READY','RUNNING',
                         'WAITING_USER','WAITING_APPROVAL','BLOCKED','RETRYING','PAUSED','VERIFYING',
                         'COMPLETED','FAILED','CANCELLED')),
  blocked_reason       TEXT CHECK (blocked_reason IS NULL OR blocked_reason IN ('EXTERNAL_EFFECT_UNKNOWN',
                         'BUDGET_EXCEEDED','PROVIDER_UNAVAILABLE','WORKSPACE_OFFLINE',
                         'HUMAN_INTERVENTION_REQUIRED','RETRY_LIMIT','NO_PROGRESS')),
  version              INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  parent_task_id       TEXT REFERENCES tasks(id),
  deadline             TEXT,
  lease_owner          TEXT,
  lease_expires_at     TEXT,
  fencing_token        INTEGER NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL,
  CHECK ((budget_amount_minor IS NULL) = (budget_currency IS NULL)),
  CHECK ((state = 'BLOCKED') = (blocked_reason IS NOT NULL)),
  CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL)),
  CHECK (lease_owner IS NULL OR state = 'RUNNING')
) STRICT;
CREATE INDEX idx_tasks_employee_state ON tasks(employee_id, state);

CREATE TABLE messages (
  id                 TEXT PRIMARY KEY,
  conversation_id    TEXT NOT NULL REFERENCES conversations(id),
  role               TEXT NOT NULL CHECK (role IN ('owner','employee','system')),
  origin             TEXT NOT NULL CHECK (origin IN ('local_app','paired_device','voice','email','system')),
  channel_id         TEXT,
  client_message_id  TEXT,
  content            TEXT NOT NULL,
  task_id            TEXT REFERENCES tasks(id),
  created_at         TEXT NOT NULL,
  UNIQUE (conversation_id, client_message_id)
) STRICT;

CREATE TABLE task_criteria (
  id            TEXT PRIMARY KEY,
  task_id       TEXT NOT NULL REFERENCES tasks(id),
  description   TEXT NOT NULL,
  required      INTEGER NOT NULL CHECK (required IN (0,1)),
  satisfied_at  TEXT,
  evidence_id   TEXT REFERENCES evidence(id)
) STRICT;

CREATE TABLE plans (
  id          TEXT PRIMARY KEY,
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  version     INTEGER NOT NULL CHECK (version >= 1),
  reason      TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE (task_id, version)
) STRICT;

CREATE TABLE steps (
  id               TEXT PRIMARY KEY,
  plan_id          TEXT NOT NULL REFERENCES plans(id),
  task_id          TEXT NOT NULL REFERENCES tasks(id),
  ordinal          INTEGER NOT NULL CHECK (ordinal >= 1),
  description      TEXT NOT NULL,
  expected_result  TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','DONE','FAILED','SKIPPED')),
  created_at       TEXT NOT NULL,
  UNIQUE (plan_id, ordinal)
) STRICT;

CREATE TABLE attempts (
  id          TEXT PRIMARY KEY,
  step_id     TEXT NOT NULL REFERENCES steps(id),
  started_at  TEXT NOT NULL,
  ended_at    TEXT,
  outcome     TEXT CHECK (outcome IS NULL OR outcome IN ('SUCCEEDED','FAILED','UNKNOWN','ABANDONED'))
) STRICT;

CREATE TABLE tools (
  tool_id        TEXT NOT NULL,
  version        TEXT NOT NULL,
  effect_class   TEXT NOT NULL CHECK (effect_class IN ('READ_ONLY','LOCAL_WRITE','EXTERNAL_WRITE','IRREVERSIBLE')),
  base_risk      TEXT NOT NULL CHECK (base_risk IN ('R0','R1','R2','R3','R4','R5')),
  manifest_json  TEXT NOT NULL,
  manifest_hash  TEXT NOT NULL,
  enabled        INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
  registered_at  TEXT NOT NULL,
  enabled_at     TEXT,
  enabled_by     TEXT,
  PRIMARY KEY (tool_id, version)
) STRICT;

CREATE TABLE actions (
  id                    TEXT PRIMARY KEY,
  task_id               TEXT NOT NULL REFERENCES tasks(id),
  step_id               TEXT,
  tool_id               TEXT NOT NULL,
  tool_version          TEXT NOT NULL,
  effect_class          TEXT NOT NULL CHECK (effect_class IN ('READ_ONLY','LOCAL_WRITE','EXTERNAL_WRITE','IRREVERSIBLE')),
  risk_class            TEXT NOT NULL CHECK (risk_class IN ('R0','R1','R2','R3','R4','R5')),
  status                TEXT NOT NULL CHECK (status IN ('PROPOSED','AUTHORIZED','DISPATCHING','CONFIRMED',
                          'FAILED','UNKNOWN','CANCELLED_BEFORE_DISPATCH')),
  input_json            TEXT NOT NULL,
  input_hash            TEXT NOT NULL,
  destination           TEXT,
  idempotency_key       TEXT UNIQUE,
  fencing_token         INTEGER,
  policy_decision       TEXT CHECK (policy_decision IS NULL OR policy_decision IN ('ALLOW','ASK','DENY')),
  policy_reason         TEXT,
  policy_version        TEXT,
  status_reason         TEXT,
  external_reference    TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL,
  dispatched_at         TEXT,
  finished_at           TEXT,
  FOREIGN KEY (tool_id, tool_version) REFERENCES tools(tool_id, version)
) STRICT;
CREATE INDEX idx_actions_task_status ON actions(task_id, status);
CREATE INDEX idx_actions_task_hash ON actions(task_id, input_hash);

CREATE TABLE external_receipts (
  id                  TEXT PRIMARY KEY,
  action_id           TEXT NOT NULL REFERENCES actions(id),
  external_reference  TEXT NOT NULL,
  receipt_json        TEXT NOT NULL,
  received_at         TEXT NOT NULL
) STRICT;

CREATE TABLE policies (
  version       TEXT PRIMARY KEY,
  rules_json    TEXT NOT NULL,
  activated_at  TEXT NOT NULL,
  activated_by  TEXT NOT NULL
) STRICT;

CREATE TABLE mandates (
  id                    TEXT PRIMARY KEY,
  owner_id              TEXT NOT NULL REFERENCES owners(id),
  employee_id           TEXT NOT NULL REFERENCES employees(id),
  tool_id               TEXT NOT NULL,
  destination_pattern   TEXT NOT NULL,
  max_risk              TEXT NOT NULL CHECK (max_risk IN ('R1','R2','R3')),
  max_cost_minor        INTEGER CHECK (max_cost_minor IS NULL OR max_cost_minor >= 0),
  max_cost_currency     TEXT,
  max_uses              INTEGER NOT NULL CHECK (max_uses >= 1),
  uses                  INTEGER NOT NULL DEFAULT 0 CHECK (uses >= 0),
  status                TEXT NOT NULL CHECK (status IN ('ACTIVE','EXHAUSTED','EXPIRED','REVOKED')),
  expires_at            TEXT NOT NULL,
  created_at            TEXT NOT NULL,
  revoked_at            TEXT,
  CHECK (uses <= max_uses),
  CHECK ((max_cost_minor IS NULL) = (max_cost_currency IS NULL))
) STRICT;

CREATE TABLE approvals (
  id                  TEXT PRIMARY KEY,
  task_id             TEXT NOT NULL REFERENCES tasks(id),
  action_id           TEXT NOT NULL REFERENCES actions(id),
  requested_by        TEXT NOT NULL CHECK (requested_by IN ('runtime','owner')),
  action_type         TEXT NOT NULL,
  destination         TEXT NOT NULL,
  params_hash         TEXT NOT NULL,
  max_cost_minor      INTEGER CHECK (max_cost_minor IS NULL OR max_cost_minor >= 0),
  max_cost_currency   TEXT,
  recurrence          TEXT NOT NULL CHECK (recurrence IN ('ONCE','MANDATE')),
  expires_at          TEXT NOT NULL,
  max_uses            INTEGER NOT NULL CHECK (max_uses >= 1),
  uses                INTEGER NOT NULL DEFAULT 0 CHECK (uses >= 0),
  policy_version      TEXT NOT NULL,
  risk_class          TEXT NOT NULL CHECK (risk_class IN ('R0','R1','R2','R3','R4')),
  status              TEXT NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED','REVOKED',
                        'RESERVED','CONSUMED')),
  nonce               TEXT NOT NULL,
  purchase_json       TEXT,
  created_at          TEXT NOT NULL,
  decided_at          TEXT,
  decided_by          TEXT,
  CHECK (uses <= max_uses),
  CHECK ((max_cost_minor IS NULL) = (max_cost_currency IS NULL))
) STRICT;
CREATE INDEX idx_approvals_action ON approvals(action_id);

CREATE TABLE approval_consumptions (
  id           TEXT PRIMARY KEY,
  approval_id  TEXT NOT NULL REFERENCES approvals(id),
  action_id    TEXT NOT NULL REFERENCES actions(id),
  status       TEXT NOT NULL CHECK (status IN ('RESERVED','CONSUMED','RELEASED','HELD_UNKNOWN')),
  reserved_at  TEXT NOT NULL,
  closed_at    TEXT,
  UNIQUE (approval_id, action_id)
) STRICT;

CREATE TABLE capability_grants (
  id           TEXT PRIMARY KEY,
  employee_id  TEXT NOT NULL REFERENCES employees(id),
  capability   TEXT NOT NULL,
  granted_by   TEXT NOT NULL,
  granted_at   TEXT NOT NULL,
  revoked_at   TEXT
) STRICT;

CREATE TABLE sources (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('owner_message','document','web','tool','system')),
  trust        TEXT NOT NULL CHECK (trust IN ('owner_authenticated','verified','untrusted')),
  ref          TEXT NOT NULL,
  captured_at  TEXT NOT NULL
) STRICT;

CREATE TABLE memories (
  id               TEXT PRIMARY KEY,
  employee_id      TEXT NOT NULL REFERENCES employees(id),
  type             TEXT NOT NULL CHECK (type IN ('IDENTITY','PREFERENCE','FACT','EPISODE','PROCEDURE')),
  status           TEXT NOT NULL CHECK (status IN ('proposed','confirmed','disputed','superseded','deleted')),
  sensitivity      TEXT NOT NULL CHECK (sensitivity IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET')),
  current_version  INTEGER NOT NULL CHECK (current_version >= 1),
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  CHECK (sensitivity <> 'SECRET')
) STRICT;

CREATE TABLE memory_versions (
  memory_id    TEXT NOT NULL REFERENCES memories(id),
  version      INTEGER NOT NULL CHECK (version >= 1),
  content      TEXT NOT NULL,
  source_id    TEXT NOT NULL REFERENCES sources(id),
  valid_from   TEXT,
  valid_until  TEXT,
  recorded_at  TEXT NOT NULL,
  PRIMARY KEY (memory_id, version)
) STRICT;

-- Derived, rebuildable index (spec 8.3). Canonical text lives in memory_versions.
CREATE VIRTUAL TABLE memory_fts USING fts5(content, memory_id UNINDEXED, tokenize = 'unicode61 remove_diacritics 2');

CREATE TABLE artifacts (
  id              TEXT PRIMARY KEY,
  employee_id     TEXT NOT NULL REFERENCES employees(id),
  task_id         TEXT REFERENCES tasks(id),
  name            TEXT NOT NULL,
  mime_type       TEXT NOT NULL,
  sha256          TEXT NOT NULL CHECK (length(sha256) = 64),
  size_bytes      INTEGER NOT NULL CHECK (size_bytes >= 0),
  storage_ref     TEXT NOT NULL,
  version         INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  classification  TEXT NOT NULL CHECK (classification IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET')),
  created_at      TEXT NOT NULL
) STRICT;

CREATE TABLE evidence (
  id           TEXT PRIMARY KEY,
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  action_id    TEXT REFERENCES actions(id),
  artifact_id  TEXT REFERENCES artifacts(id),
  kind         TEXT NOT NULL CHECK (kind IN ('provider_receipt','artifact_hash','file_opens','deterministic_check',
                 'source_check','human_confirmation','reconciliation')),
  summary      TEXT NOT NULL,
  created_at   TEXT NOT NULL
) STRICT;

CREATE TABLE artifact_links (
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  relation     TEXT NOT NULL CHECK (relation IN ('input','output','evidence')),
  PRIMARY KEY (artifact_id, task_id, relation)
) STRICT;

CREATE TABLE deliveries (
  id                  TEXT PRIMARY KEY,
  task_id             TEXT NOT NULL REFERENCES tasks(id),
  artifact_id         TEXT NOT NULL REFERENCES artifacts(id),
  action_id           TEXT REFERENCES actions(id),
  channel             TEXT NOT NULL,
  status              TEXT NOT NULL CHECK (status IN ('PENDING','SENT','UNKNOWN','FAILED')),
  external_reference  TEXT,
  created_at          TEXT NOT NULL
) STRICT;

CREATE TABLE skills (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  created_at  TEXT NOT NULL
) STRICT;

CREATE TABLE skill_versions (
  skill_id      TEXT NOT NULL REFERENCES skills(id),
  version       TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('DRAFT','TESTED','PROMOTED','ROLLED_BACK')),
  created_at    TEXT NOT NULL,
  PRIMARY KEY (skill_id, version)
) STRICT;

CREATE TABLE journal_events (
  sequence_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id           TEXT NOT NULL UNIQUE,
  timestamp          TEXT NOT NULL,
  employee_id        TEXT NOT NULL,
  task_id            TEXT,
  action_id          TEXT,
  actor_kind         TEXT NOT NULL,
  actor_id           TEXT NOT NULL,
  type               TEXT NOT NULL,
  policy_version     TEXT,
  model_provider     TEXT,
  model_id           TEXT,
  duration_ms        INTEGER,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  summary            TEXT NOT NULL
) STRICT;
CREATE INDEX idx_journal_employee_seq ON journal_events(employee_id, sequence_id);

-- The audit journal is append-only.
CREATE TRIGGER journal_no_update BEFORE UPDATE ON journal_events
BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END;
CREATE TRIGGER journal_no_delete BEFORE DELETE ON journal_events
BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END;

-- Material parameters of an approval or action can never be rewritten in place.
CREATE TRIGGER approvals_immutable_terms BEFORE UPDATE OF task_id, action_id, action_type, destination,
  params_hash, max_cost_minor, max_cost_currency, recurrence, max_uses, risk_class, nonce, purchase_json
  ON approvals
BEGIN SELECT RAISE(ABORT, 'approval terms are immutable; create a new approval'); END;
CREATE TRIGGER actions_immutable_input BEFORE UPDATE OF task_id, tool_id, tool_version, input_json, input_hash,
  destination, effect_class, risk_class ON actions
BEGIN SELECT RAISE(ABORT, 'action input is immutable'); END;

CREATE TABLE checkpoints (
  id          TEXT PRIMARY KEY,
  task_id     TEXT NOT NULL REFERENCES tasks(id),
  state_json  TEXT NOT NULL,
  created_at  TEXT NOT NULL
) STRICT;

CREATE TABLE scheduled_jobs (
  id                TEXT PRIMARY KEY,
  employee_id       TEXT NOT NULL REFERENCES employees(id),
  template_json     TEXT NOT NULL,
  timezone          TEXT NOT NULL,
  interval_minutes  INTEGER NOT NULL CHECK (interval_minutes >= 1),
  next_run_at       TEXT NOT NULL,
  missed_policy     TEXT NOT NULL CHECK (missed_policy IN ('CONSOLIDATE_AND_CONFIRM','SKIP','RUN_ONCE')),
  dedup_key         TEXT NOT NULL UNIQUE,
  last_run_at       TEXT,
  enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1))
) STRICT;

CREATE TABLE budget_reservations (
  id               TEXT PRIMARY KEY,
  task_id          TEXT REFERENCES tasks(id),
  category         TEXT NOT NULL CHECK (category IN ('inference','paid_tool','purchase')),
  period_key       TEXT NOT NULL,
  amount_minor     INTEGER NOT NULL CHECK (amount_minor >= 0),
  currency         TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('RESERVED','SETTLED','RELEASED')),
  settled_minor    INTEGER CHECK (settled_minor IS NULL OR settled_minor >= 0),
  created_at       TEXT NOT NULL,
  closed_at        TEXT
) STRICT;
CREATE INDEX idx_budget_period ON budget_reservations(category, period_key, status);
CREATE INDEX idx_budget_task ON budget_reservations(task_id, status);

CREATE TABLE usage_ledger (
  id                TEXT PRIMARY KEY,
  reservation_id    TEXT REFERENCES budget_reservations(id),
  task_id           TEXT REFERENCES tasks(id),
  provider          TEXT NOT NULL,
  model_id          TEXT,
  request_id        TEXT,
  category          TEXT NOT NULL CHECK (category IN ('inference','paid_tool','purchase')),
  input_tokens      INTEGER,
  cached_tokens     INTEGER,
  output_tokens     INTEGER,
  estimated_minor   INTEGER NOT NULL CHECK (estimated_minor >= 0),
  reported_minor    INTEGER CHECK (reported_minor IS NULL OR reported_minor >= 0),
  currency          TEXT NOT NULL,
  price_table       TEXT,
  created_at        TEXT NOT NULL
) STRICT;

CREATE TABLE credential_refs (
  id                         TEXT PRIMARY KEY,
  owner_id                   TEXT NOT NULL REFERENCES owners(id),
  provider                   TEXT NOT NULL,
  scope                      TEXT NOT NULL,
  purpose                    TEXT NOT NULL,
  allowed_destinations_json  TEXT NOT NULL,
  backend                    TEXT NOT NULL,
  backend_locator            TEXT NOT NULL,
  expires_at                 TEXT,
  created_at                 TEXT NOT NULL,
  revoked_at                 TEXT
) STRICT;

CREATE TABLE browser_sessions (
  id                 TEXT PRIMARY KEY,
  credential_ref_id  TEXT REFERENCES credential_refs(id),
  profile            TEXT NOT NULL CHECK (profile IN ('public_research','operational','high_impact')),
  created_at         TEXT NOT NULL,
  expires_at         TEXT
) STRICT;

CREATE TABLE settings (
  revision     INTEGER PRIMARY KEY,
  config_json  TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  updated_by   TEXT NOT NULL
) STRICT;
