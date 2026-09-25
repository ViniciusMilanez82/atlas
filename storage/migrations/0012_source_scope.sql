-- Contract v2 A3-26: a source belongs to one employee scope, so a memory can never cite (or be
-- corrected with) a source of another employee. Legacy rows take the employee of the memories citing them.
ALTER TABLE sources ADD COLUMN employee_id TEXT REFERENCES employees(id);
UPDATE sources SET employee_id = (
  SELECT m.employee_id FROM memory_versions v JOIN memories m ON m.id = v.memory_id
  WHERE v.source_id = sources.id LIMIT 1
) WHERE employee_id IS NULL;
