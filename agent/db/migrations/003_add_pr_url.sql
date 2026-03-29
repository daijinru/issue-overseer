-- Add pr_url column to issues table (nullable, stores the PR URL after creation)
ALTER TABLE issues ADD COLUMN pr_url TEXT;
