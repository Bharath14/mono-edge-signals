-- Supabase only: run once after the schema exists (safe to repeat).
--
-- Supabase serves every table in the public schema over its REST API, and the
-- anon key that API accepts is public (it ships to the browser for login).
-- The app never uses that API: its server routes connect to Postgres directly
-- as the owner role. So the API roles get no access to any table, including
-- partitions the pipeline creates later.

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;

-- Belt and braces: row level security with no policies denies everything to
-- non-owner roles even if a grant comes back.
ALTER TABLE raw_readings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_readings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE historical_rollups  ENABLE ROW LEVEL SECURITY;
ALTER TABLE rejected_readings   ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents           ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident_snapshots  ENABLE ROW LEVEL SECURITY;
