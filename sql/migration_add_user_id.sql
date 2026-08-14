-- Synap multi-user memory isolation (run once in CockroachDB SQL Shell)

ALTER TABLE diary_entries
  ADD COLUMN IF NOT EXISTS user_id STRING NOT NULL DEFAULT 'default_user';

ALTER TABLE life_vector_memory
  ADD COLUMN IF NOT EXISTS user_id STRING NOT NULL DEFAULT 'default_user';

CREATE INDEX IF NOT EXISTS idx_diary_entries_user_id
  ON diary_entries (user_id);

CREATE INDEX IF NOT EXISTS idx_life_vector_memory_user_id
  ON life_vector_memory (user_id);

-- Optional: prefix column helps vector ANN when filtering by user at scale
-- DROP INDEX IF EXISTS life_vector_memory@life_vector_memory_emotional_vector_idx;
-- CREATE VECTOR INDEX life_vector_memory_user_vector_idx
--   ON life_vector_memory (user_id, emotional_vector vector_cosine_ops);
