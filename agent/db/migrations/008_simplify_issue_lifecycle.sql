-- Store the simplified Issue API alongside legacy columns so existing data can
-- migrate without loss while callers move to the project/content lifecycle.
ALTER TABLE issues ADD COLUMN project TEXT NOT NULL DEFAULT '';
ALTER TABLE issues ADD COLUMN content TEXT NOT NULL DEFAULT '';
ALTER TABLE issues ADD COLUMN outcome TEXT CHECK(outcome IN ('success', 'error'));
ALTER TABLE issues ADD COLUMN result TEXT;
ALTER TABLE issues ADD COLUMN finished_at TEXT;

UPDATE issues SET content = description WHERE content = '';
UPDATE issues
SET status = 'pending'
WHERE status IN ('open', 'planning', 'planned', 'waiting_human', 'cancelled');
UPDATE issues SET status = 'finished' WHERE status IN ('review', 'done');
