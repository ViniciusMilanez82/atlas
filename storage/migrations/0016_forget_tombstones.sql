-- Contract v2 A3-17: forgetting is recorded without the forgotten content. A tombstone lists what was
-- erased or withheld (ids) and the hashes of the content, so a restore can re-apply it and a derived
-- source (summary, document, tool output) cannot bring the same content back.
CREATE TABLE forget_tombstones (
  id                    TEXT PRIMARY KEY,
  employee_id           TEXT NOT NULL REFERENCES employees(id),
  memory_id             TEXT REFERENCES memories(id),
  scope                 TEXT NOT NULL CHECK (scope IN ('stop_using','erase')),
  content_hashes_json   TEXT NOT NULL,
  message_ids_json      TEXT NOT NULL,
  observation_ids_json  TEXT NOT NULL,
  created_at            TEXT NOT NULL
) STRICT;
CREATE INDEX idx_tombstones_employee ON forget_tombstones(employee_id);
-- 'Nao use mais isto': the message stays visible to the owner but never goes into a model context.
ALTER TABLE messages ADD COLUMN context_excluded INTEGER NOT NULL DEFAULT 0 CHECK (context_excluded IN (0,1));
