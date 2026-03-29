-- Mango schema v1: issues, executions, execution_logs

CREATE TABLE issues (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open', 'running', 'done', 'failed', 'waiting_human', 'cancelled')),
  branch_name TEXT,
  human_instruction TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE executions (
  id TEXT PRIMARY KEY,
  issue_id TEXT NOT NULL REFERENCES issues(id),
  turn_number INTEGER NOT NULL,
  attempt_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK(status IN ('running', 'completed', 'failed', 'cancelled', 'timeout')),
  prompt TEXT,
  result TEXT,
  error_message TEXT,
  context_snapshot TEXT,
  git_diff_snapshot TEXT,
  duration_ms INTEGER,
  started_at TEXT DEFAULT (datetime('now')),
  finished_at TEXT
);

CREATE TABLE execution_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT NOT NULL REFERENCES executions(id),
  level TEXT NOT NULL DEFAULT 'info'
    CHECK(level IN ('info', 'warn', 'error')),
  message TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_exec_issue ON executions(issue_id);
CREATE INDEX idx_logs_exec ON execution_logs(execution_id);
