-- Add workspace column to issues table (nullable, defaults to NULL = use global config)
ALTER TABLE issues ADD COLUMN workspace TEXT;
