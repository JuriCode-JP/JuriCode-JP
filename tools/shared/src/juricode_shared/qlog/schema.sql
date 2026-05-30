-- JuriCode-JP qlog schema (Phase A).
-- PRAGMA journal_mode / busy_timeout / foreign_keys are set per-connection in
-- store._connect (NOT here): executescript issues an implicit COMMIT, and WAL is
-- a connection-layer concern. Keeping DDL pure avoids transaction surprises.

CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  asked_at TEXT NOT NULL,
  question_text TEXT,
  question_text_anonymized TEXT,
  pii_detected INTEGER NOT NULL,
  pii_pattern_matched TEXT,
  k INTEGER NOT NULL,
  embedder TEXT NOT NULL,
  corpus_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
  question_id TEXT NOT NULL,
  rank INTEGER NOT NULL,
  article_id TEXT NOT NULL,
  score REAL NOT NULL,
  PRIMARY KEY (question_id, rank),
  FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  given_at TEXT NOT NULL,
  signal TEXT NOT NULL CHECK (signal IN ('good', 'bad')),
  comment TEXT,
  comment_anonymized TEXT,
  FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS clicks (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  clicked_at TEXT NOT NULL,
  rank INTEGER NOT NULL,
  article_id TEXT NOT NULL,
  dwell_seconds REAL,
  dwell_seconds_raw REAL,
  FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
CREATE INDEX IF NOT EXISTS idx_questions_asked_at ON questions(asked_at);
CREATE INDEX IF NOT EXISTS idx_results_article ON results(article_id);
CREATE INDEX IF NOT EXISTS idx_clicks_question ON clicks(question_id);
