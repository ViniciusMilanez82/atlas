-- Setup progress is local-owner state, never a claim that unimplemented features are ready.
CREATE TABLE onboarding_progress (
  employee_id TEXT PRIMARY KEY REFERENCES employees(id),
  step TEXT NOT NULL CHECK (step IN ('welcome','identity','intelligence','privacy','done')),
  updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE product_receipts (
  employee_id TEXT NOT NULL REFERENCES employees(id),
  request_id TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (employee_id, request_id)
) STRICT;
