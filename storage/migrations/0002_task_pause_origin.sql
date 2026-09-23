-- Remember where a paused task came from so resume can re-evaluate instead of guessing (spec 3.4, 9.2).
ALTER TABLE tasks ADD COLUMN paused_from TEXT
  CHECK ((paused_from IS NULL) = (state <> 'PAUSED'));
