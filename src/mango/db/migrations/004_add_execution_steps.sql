-- Add execution_steps table for persisting real-time OpenCode step events.

CREATE TABLE execution_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT NOT NULL REFERENCES executions(id),
  step_type TEXT NOT NULL CHECK(step_type IN ('tool_use', 'text', 'step')),
  tool TEXT,
  target TEXT,
  summary TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_steps_exec ON execution_steps(execution_id);
