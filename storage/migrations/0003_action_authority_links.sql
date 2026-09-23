-- Link each action to the authority it consumed so settlement and reconciliation are exact (spec 12.1).
ALTER TABLE actions ADD COLUMN approval_id TEXT REFERENCES approvals(id);
ALTER TABLE actions ADD COLUMN mandate_id TEXT REFERENCES mandates(id);
ALTER TABLE actions ADD COLUMN budget_reservation_id TEXT REFERENCES budget_reservations(id);
ALTER TABLE actions ADD COLUMN worker_id TEXT;
