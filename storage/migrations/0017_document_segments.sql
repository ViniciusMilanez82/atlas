-- Contract v2 A3-09 / A3-10: what was understood from each artifact, with provenance, and what each
-- task actually read (coverage). The original stays immutable in the artifact store.
CREATE TABLE document_extractions (
  artifact_id        TEXT PRIMARY KEY REFERENCES artifacts(id),
  state              TEXT NOT NULL CHECK (state IN ('READY_FOR_ANALYSIS','PARTIAL','UNSUPPORTED','FAILED')),
  extractor          TEXT NOT NULL,
  extractor_version  TEXT NOT NULL,
  segment_count      INTEGER NOT NULL CHECK (segment_count >= 0),
  total_chars        INTEGER NOT NULL CHECK (total_chars >= 0),
  warnings_json      TEXT NOT NULL,
  diagnostic         TEXT,
  created_at         TEXT NOT NULL
) STRICT;
CREATE TABLE document_segments (
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  seq          INTEGER NOT NULL CHECK (seq >= 0),
  locator      TEXT NOT NULL,
  kind         TEXT NOT NULL CHECK (kind IN ('text','table','notes','header','footer','cells')),
  text         TEXT NOT NULL,
  PRIMARY KEY (artifact_id, seq)
) STRICT;
CREATE VIRTUAL TABLE document_fts USING fts5(text, artifact_id UNINDEXED, seq UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2');
CREATE TABLE document_reads (
  task_id      TEXT NOT NULL REFERENCES tasks(id),
  artifact_id  TEXT NOT NULL REFERENCES artifacts(id),
  seq          INTEGER NOT NULL,
  read_at      TEXT NOT NULL,
  PRIMARY KEY (task_id, artifact_id, seq)
) STRICT;
