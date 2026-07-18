ALTER TABLE issues ADD COLUMN agent TEXT NOT NULL DEFAULT 'wiscode'
  CHECK(agent IN ('wiscode'));
