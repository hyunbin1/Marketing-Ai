from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from launchpilot.persistence.tenant import current_workspace_id

_MIGRATIONS = (
    (
        1,
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            google_subject TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            display_name TEXT,
            created_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE workspaces (
            id UUID PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE workspace_memberships (
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(workspace_id, user_id)
        );
        CREATE INDEX workspace_memberships_user_idx
            ON workspace_memberships(user_id);

        CREATE TABLE platform_connections (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            account_ref TEXT,
            granted_scopes JSONB NOT NULL,
            encrypted_token TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(user_id, provider)
        );

        CREATE TABLE campaigns (
            id UUID PRIMARY KEY,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            goal TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            target_metrics JSONB NOT NULL,
            resource_bindings JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CHECK (period_start <= period_end)
        );
        CREATE INDEX campaigns_workspace_created_idx
            ON campaigns(workspace_id, created_at);

        CREATE TABLE conversations (
            id UUID PRIMARY KEY,
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX conversations_campaign_created_idx
            ON conversations(campaign_id, created_at);

        CREATE TABLE campaign_observations (
            id UUID PRIMARY KEY,
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            completeness_status TEXT NOT NULL,
            missing_reasons JSONB NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            CHECK (period_start <= period_end),
            CHECK (completeness_status IN ('COMPLETE', 'PARTIAL'))
        );
        CREATE INDEX observations_campaign_captured_idx
            ON campaign_observations(campaign_id, captured_at);

        CREATE TABLE platform_slices (
            observation_id UUID NOT NULL
                REFERENCES campaign_observations(id) ON DELETE CASCADE,
            slice_index INTEGER NOT NULL,
            surface TEXT NOT NULL,
            connector TEXT NOT NULL,
            account_ref TEXT NOT NULL,
            fetch_run_ref TEXT NOT NULL,
            external_campaign_ref TEXT,
            currency_code TEXT,
            timezone TEXT,
            attribution_setting TEXT,
            PRIMARY KEY(observation_id, slice_index)
        );

        CREATE TABLE metric_observations (
            observation_id UUID NOT NULL,
            slice_index INTEGER NOT NULL,
            metric_index INTEGER NOT NULL,
            subject_ref TEXT NOT NULL,
            subject_level TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            unit TEXT NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            provenance_ref TEXT NOT NULL,
            calculation TEXT,
            PRIMARY KEY(observation_id, slice_index, metric_index),
            FOREIGN KEY(observation_id, slice_index)
                REFERENCES platform_slices(observation_id, slice_index)
                ON DELETE CASCADE,
            CHECK (period_start <= period_end)
        );
        CREATE INDEX metrics_key_subject_idx
            ON metric_observations(metric_key, subject_ref);

        CREATE TABLE external_campaign_bindings (
            id UUID PRIMARY KEY,
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            connection_id UUID NOT NULL
                REFERENCES platform_connections(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            external_account_ref TEXT NOT NULL,
            external_campaign_ref TEXT NOT NULL,
            display_name TEXT NOT NULL,
            currency_code TEXT,
            timezone TEXT,
            attribution_setting TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(campaign_id, connection_id, external_campaign_ref)
        );
        """,
    ),
    (
        2,
        """
        CREATE TABLE campaign_documents (
            id UUID PRIMARY KEY,
            campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(campaign_id, source_ref),
            CHECK (document_type IN ('MEMO', 'BRIEF', 'ANALYSIS'))
        );
        CREATE INDEX campaign_documents_scope_created_idx
            ON campaign_documents(workspace_id, campaign_id, created_at);
        """,
    ),
    (
        3,
        """
        CREATE TABLE retrieval_experiment_runs (
            id UUID PRIMARY KEY,
            matrix_version TEXT NOT NULL,
            golden_version TEXT NOT NULL,
            corpus_version TEXT NOT NULL,
            split TEXT NOT NULL,
            chunker_method TEXT NOT NULL,
            chunker_version TEXT NOT NULL,
            chunker_config JSONB NOT NULL,
            retriever_method TEXT NOT NULL,
            retriever_version TEXT NOT NULL,
            retriever_config JSONB NOT NULL,
            status TEXT NOT NULL,
            block_reason TEXT,
            document_count INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            eligible_case_count INTEGER NOT NULL,
            aggregate_metrics JSONB NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            CHECK (split IN ('tune', 'validation', 'holdout')),
            CHECK (status IN ('pending', 'running', 'completed', 'blocked', 'failed')),
            CHECK (document_count >= 0),
            CHECK (chunk_count >= 0),
            CHECK (eligible_case_count >= 0)
        );
        CREATE INDEX retrieval_experiment_runs_matrix_idx
            ON retrieval_experiment_runs(matrix_version, split, status);

        CREATE TABLE retrieval_experiment_case_results (
            experiment_id UUID NOT NULL
                REFERENCES retrieval_experiment_runs(id) ON DELETE CASCADE,
            case_id TEXT NOT NULL,
            query_profile TEXT NOT NULL,
            taxonomy JSONB NOT NULL,
            latency_ms DOUBLE PRECISION NOT NULL,
            retrieved JSONB NOT NULL,
            metrics JSONB NOT NULL,
            PRIMARY KEY(experiment_id, case_id),
            CHECK (latency_ms >= 0)
        );
        CREATE INDEX retrieval_experiment_cases_profile_idx
            ON retrieval_experiment_case_results(query_profile);

        CREATE TABLE retrieval_experiment_slice_metrics (
            experiment_id UUID NOT NULL
                REFERENCES retrieval_experiment_runs(id) ON DELETE CASCADE,
            dimension TEXT NOT NULL,
            value TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value DOUBLE PRECISION NOT NULL,
            sample_size INTEGER NOT NULL,
            PRIMARY KEY(experiment_id, dimension, value, metric_name),
            CHECK (sample_size > 0)
        );
        CREATE INDEX retrieval_experiment_slice_lookup_idx
            ON retrieval_experiment_slice_metrics(dimension, value, metric_name);
        """,
    ),
    (
        4,
        """
        ALTER TABLE retrieval_experiment_runs
            ADD COLUMN execution_id UUID;
        UPDATE retrieval_experiment_runs
            SET execution_id = id
            WHERE execution_id IS NULL;
        ALTER TABLE retrieval_experiment_runs
            ALTER COLUMN execution_id SET NOT NULL;
        CREATE INDEX retrieval_experiment_runs_execution_idx
            ON retrieval_experiment_runs(execution_id, split, status);
        """,
    ),
    (
        5,
        """
        -- Tenant isolation foundation (Step 1a).
        -- Denormalize workspace_id onto every tenant table so each RLS policy is a
        -- single equality, then enable Row-Level Security. This migration is applied
        -- by the superuser and does NOT break the app: while the runtime still
        -- connects as the superuser it bypasses RLS. Enforcement is switched on in
        -- Step 1b by connecting the runtime as the non-superuser app_user role.

        -- 1) Backfill workspace_id on tables that only reference a campaign.
        ALTER TABLE conversations ADD COLUMN IF NOT EXISTS workspace_id UUID;
        UPDATE conversations c
            SET workspace_id = ca.workspace_id
            FROM campaigns ca
            WHERE ca.id = c.campaign_id AND c.workspace_id IS NULL;
        ALTER TABLE conversations ALTER COLUMN workspace_id SET NOT NULL;

        ALTER TABLE campaign_observations ADD COLUMN IF NOT EXISTS workspace_id UUID;
        UPDATE campaign_observations o
            SET workspace_id = ca.workspace_id
            FROM campaigns ca
            WHERE ca.id = o.campaign_id AND o.workspace_id IS NULL;
        ALTER TABLE campaign_observations ALTER COLUMN workspace_id SET NOT NULL;

        ALTER TABLE external_campaign_bindings ADD COLUMN IF NOT EXISTS workspace_id UUID;
        UPDATE external_campaign_bindings b
            SET workspace_id = ca.workspace_id
            FROM campaigns ca
            WHERE ca.id = b.campaign_id AND b.workspace_id IS NULL;
        ALTER TABLE external_campaign_bindings ALTER COLUMN workspace_id SET NOT NULL;

        -- 2) Backfill the deep metric tables through campaign_observations.
        ALTER TABLE platform_slices ADD COLUMN IF NOT EXISTS workspace_id UUID;
        UPDATE platform_slices ps
            SET workspace_id = ca.workspace_id
            FROM campaign_observations co
            JOIN campaigns ca ON ca.id = co.campaign_id
            WHERE co.id = ps.observation_id AND ps.workspace_id IS NULL;
        ALTER TABLE platform_slices ALTER COLUMN workspace_id SET NOT NULL;

        ALTER TABLE metric_observations ADD COLUMN IF NOT EXISTS workspace_id UUID;
        UPDATE metric_observations m
            SET workspace_id = ca.workspace_id
            FROM campaign_observations co
            JOIN campaigns ca ON ca.id = co.campaign_id
            WHERE co.id = m.observation_id AND m.workspace_id IS NULL;
        ALTER TABLE metric_observations ALTER COLUMN workspace_id SET NOT NULL;

        -- 3) Foreign keys + indexes for the backfilled columns (idempotent).
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversations_workspace_fk') THEN
                ALTER TABLE conversations
                    ADD CONSTRAINT conversations_workspace_fk
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'campaign_observations_workspace_fk') THEN
                ALTER TABLE campaign_observations
                    ADD CONSTRAINT campaign_observations_workspace_fk
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'external_campaign_bindings_workspace_fk') THEN
                ALTER TABLE external_campaign_bindings
                    ADD CONSTRAINT external_campaign_bindings_workspace_fk
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE;
            END IF;
        END $$;

        CREATE INDEX IF NOT EXISTS conversations_workspace_idx ON conversations(workspace_id);
        CREATE INDEX IF NOT EXISTS campaign_observations_workspace_idx ON campaign_observations(workspace_id);
        CREATE INDEX IF NOT EXISTS external_campaign_bindings_workspace_idx ON external_campaign_bindings(workspace_id);
        CREATE INDEX IF NOT EXISTS platform_slices_workspace_idx ON platform_slices(workspace_id);
        CREATE INDEX IF NOT EXISTS metric_observations_workspace_idx ON metric_observations(workspace_id);

        -- 4) Enable Row-Level Security + tenant policies on every tenant table.
        --    The policy reads app.workspace_id set per request via SET LOCAL; when it
        --    is unset the comparison is NULL, so no rows match (fail-closed).
        ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS campaigns_tenant_isolation ON campaigns;
        CREATE POLICY campaigns_tenant_isolation ON campaigns
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        ALTER TABLE campaign_documents ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS campaign_documents_tenant_isolation ON campaign_documents;
        CREATE POLICY campaign_documents_tenant_isolation ON campaign_documents
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS conversations_tenant_isolation ON conversations;
        CREATE POLICY conversations_tenant_isolation ON conversations
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        ALTER TABLE campaign_observations ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS campaign_observations_tenant_isolation ON campaign_observations;
        CREATE POLICY campaign_observations_tenant_isolation ON campaign_observations
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        ALTER TABLE platform_slices ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS platform_slices_tenant_isolation ON platform_slices;
        CREATE POLICY platform_slices_tenant_isolation ON platform_slices
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        ALTER TABLE metric_observations ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS metric_observations_tenant_isolation ON metric_observations;
        CREATE POLICY metric_observations_tenant_isolation ON metric_observations
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        ALTER TABLE external_campaign_bindings ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS external_campaign_bindings_tenant_isolation ON external_campaign_bindings;
        CREATE POLICY external_campaign_bindings_tenant_isolation ON external_campaign_bindings
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
            WITH CHECK (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid);

        -- 5) Create the non-superuser runtime role and grant it least-privilege DML.
        --    NOSUPERUSER + NOBYPASSRLS is what makes RLS actually apply to the app.
        --    LOGIN + password are provisioned per environment in Step 1b.
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOLOGIN;
            END IF;
        END $$;
        GRANT USAGE ON SCHEMA public TO app_user;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO app_user;
        """,
    ),
)


class PostgresDatabase:
    """Shared PostgreSQL connection boundary and minimal schema migrations.

    ``set_tenant_guc`` makes every connection stamp the active request's workspace
    onto the transaction-local ``app.workspace_id`` GUC that RLS policies read; the
    runtime app store enables it while the admin store (migrations, seeding, auth
    lookups) leaves it off so it keeps bypassing RLS as the superuser.
    """

    def __init__(
        self,
        database_url: str,
        *,
        set_tenant_guc: bool = False,
        run_migrations: bool = True,
    ) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must use PostgreSQL")
        self.database_url = database_url
        self._set_tenant_guc = set_tenant_guc
        if run_migrations:
            self._initialize()

    @contextmanager
    def connect(self) -> Iterator[Connection[dict[str, object]]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            if self._set_tenant_guc:
                workspace_id = current_workspace_id()
                if workspace_id is not None:
                    # Transaction-local (is_local=true), so it never leaks to the
                    # next borrower of a pooled connection.
                    connection.execute(
                        "SELECT set_config('app.workspace_id', %s, true)",
                        (workspace_id,),
                    )
            yield connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext('launchpilot_schema_migrations'))"
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for version, sql in _MIGRATIONS:
                if version in applied:
                    continue
                connection.execute(sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
                )
