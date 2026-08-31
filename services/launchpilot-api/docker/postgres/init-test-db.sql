CREATE DATABASE launchpilot_test;
CREATE DATABASE launchpilot_mock;

-- Non-superuser runtime role for local development. RLS only applies to a role
-- that is neither the superuser nor the table owner, so the app connects as this
-- role (via APP_DATABASE_URL) to get tenant isolation enforced. Cluster-wide, so
-- it is visible from every database; per-table GRANTs are applied by migration v5.
-- Production provisions this role with a real secret out of band.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user LOGIN PASSWORD 'app-user-local'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END $$;
