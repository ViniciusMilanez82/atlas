-- R5-01 (review of PR #5): classification and origin travel with instructions, notifications and the
-- messages that echo a task. Missing metadata is handled explicitly and conservatively: nothing is
-- silently downgraded. Rank order: PUBLIC < INTERNAL < PERSONAL < SENSITIVE < SECRET, computed with
-- instr() over that list (positions are monotonic).

-- Instruction revisions: the class of the owner's words. Rows with a source message inherit it; rows
-- without one stay NULL = legacy, re-derived from their text by trusted code at read time
-- (security/egress/lineage.py) and never assumed INTERNAL.
ALTER TABLE task_instruction_versions ADD COLUMN classification TEXT
  CHECK (classification IS NULL OR classification IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET'));
UPDATE task_instruction_versions
  SET classification = (SELECT m.classification FROM messages m WHERE m.id = task_instruction_versions.source_message_id)
  WHERE source_message_id IS NOT NULL;

-- A task whose instructions came from a more protected message is at least that protected.
UPDATE tasks SET data_policy = (
    SELECT m.classification FROM task_instruction_versions v JOIN messages m ON m.id = v.source_message_id
    WHERE v.task_id = tasks.id
    ORDER BY instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', m.classification) DESC LIMIT 1)
  WHERE instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', data_policy) < (
    SELECT MAX(instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', m.classification))
    FROM task_instruction_versions v JOIN messages m ON m.id = v.source_message_id WHERE v.task_id = tasks.id);

-- Notifications keep class and origin from the commit that queued them to the delivered message.
ALTER TABLE notification_outbox ADD COLUMN classification TEXT NOT NULL DEFAULT 'INTERNAL'
  CHECK (classification IN ('PUBLIC','INTERNAL','PERSONAL','SENSITIVE','SECRET'));
ALTER TABLE notification_outbox ADD COLUMN source_ref TEXT;
UPDATE notification_outbox SET classification = (SELECT t.data_policy FROM tasks t WHERE t.id = notification_outbox.task_id)
  WHERE task_id IS NOT NULL AND instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', classification) <
    instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', (SELECT t.data_policy FROM tasks t WHERE t.id = notification_outbox.task_id));
ALTER TABLE messages ADD COLUMN source_ref TEXT;

-- Messages of the employee that talk about a task (acks, questions, results) echo its content: they
-- are at least as protected as the task.
UPDATE messages SET classification = (SELECT t.data_policy FROM tasks t WHERE t.id = messages.task_id)
  WHERE role = 'employee' AND task_id IS NOT NULL
    AND instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', classification) <
        instr('PUBLIC,INTERNAL,PERSONAL,SENSITIVE,SECRET', (SELECT t.data_policy FROM tasks t WHERE t.id = messages.task_id));
