-- Contract v2 A3-02: classification travels with every piece of content that can reach a model.
-- Messages and step observations keep the classification of what they contain (derived content
-- inherits at least the protection of its inputs, spec 9.1). Unknown is never PUBLIC.
ALTER TABLE messages ADD COLUMN classification TEXT NOT NULL DEFAULT 'INTERNAL'
  CHECK (classification IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET'));
ALTER TABLE step_observations ADD COLUMN classification TEXT NOT NULL DEFAULT 'INTERNAL'
  CHECK (classification IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET'));
-- Memory proposals of sensitive content and their confirmation echo were stored as plain chat before.
UPDATE messages SET classification = 'SENSITIVE'
  WHERE memory_id IN (SELECT id FROM memories WHERE sensitivity = 'SENSITIVE');
