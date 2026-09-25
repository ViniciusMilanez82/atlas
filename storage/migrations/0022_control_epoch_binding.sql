-- R5-03 (review of PR #5): "stop everything" also invalidates work still being interpreted. Every
-- durable request records the control epoch in force when it was RECEIVED; every task records the
-- epoch under which the owner authorized it. Publication, lease and dispatch compare it with the
-- employee's current epoch: a late result of an interpretation started before STOP is published
-- PAUSED (visible, resumable by the owner), never executable. See ADR-017.
ALTER TABLE request_receipts ADD COLUMN control_epoch INTEGER CHECK (control_epoch IS NULL OR control_epoch >= 0);
ALTER TABLE tasks ADD COLUMN control_epoch INTEGER NOT NULL DEFAULT 0 CHECK (control_epoch >= 0);
-- Existing tasks: every non-paused one was authorized under the current epoch (stop-all pauses all of
-- them atomically when it bumps the epoch), and paused ones need the owner's resume anyway.
UPDATE tasks SET control_epoch = (SELECT e.control_epoch FROM employees e WHERE e.id = tasks.employee_id);
-- Receipts already stored belong to the epoch in force now (none can be pending across a STOP here:
-- the stop-all order is recorded, and a resumed old receipt is conservatively bound to epoch 0).
UPDATE request_receipts SET control_epoch = 0 WHERE state IN ('RECEIVED','PROCESSING');
UPDATE request_receipts SET control_epoch = (SELECT e.control_epoch FROM employees e WHERE e.id = request_receipts.employee_id)
  WHERE state NOT IN ('RECEIVED','PROCESSING');
