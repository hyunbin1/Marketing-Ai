"""Structural verification for the Step 1a tenant-isolation migration.

These tests require PostgreSQL (they build a PostgresDatabase, which applies the
migrations). Run them with `docker compose up -d postgres` first. They assert the
schema/RLS shape the migration establishes; behavioural RLS enforcement (queries
returning only a tenant's rows) is exercised in Step 1b once the runtime connects
as the non-superuser app_user role.
"""

from __future__ import annotations

TENANT_TABLES = (
    "campaigns",
    "campaign_documents",
    "conversations",
    "campaign_observations",
    "platform_slices",
    "metric_observations",
    "external_campaign_bindings",
)

BACKFILLED_TABLES = (
    "conversations",
    "campaign_observations",
    "platform_slices",
    "metric_observations",
    "external_campaign_bindings",
)


def test_workspace_id_columns_exist_and_are_not_null(postgres_database) -> None:
    with postgres_database.connect() as connection:
        for table in BACKFILLED_TABLES:
            row = connection.execute(
                """SELECT is_nullable FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                      AND column_name = 'workspace_id'""",
                (table,),
            ).fetchone()
            assert row is not None, f"{table}.workspace_id column is missing"
            assert row["is_nullable"] == "NO", f"{table}.workspace_id should be NOT NULL"


def test_rls_is_enabled_on_every_tenant_table(postgres_database) -> None:
    with postgres_database.connect() as connection:
        for table in TENANT_TABLES:
            row = connection.execute(
                "SELECT relrowsecurity FROM pg_class WHERE relname = %s",
                (table,),
            ).fetchone()
            assert row is not None, f"table {table} not found"
            assert row["relrowsecurity"] is True, f"RLS not enabled on {table}"


def test_each_tenant_table_has_an_isolation_policy(postgres_database) -> None:
    with postgres_database.connect() as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_policies WHERE schemaname = 'public'"
        ).fetchall()
        tables_with_policy = {row["tablename"] for row in rows}
        for table in TENANT_TABLES:
            assert table in tables_with_policy, f"no RLS policy on {table}"


def test_app_user_role_cannot_bypass_rls(postgres_database) -> None:
    with postgres_database.connect() as connection:
        row = connection.execute(
            """SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'app_user'"""
        ).fetchone()
        assert row is not None, "app_user role was not created"
        assert row["rolsuper"] is False, "app_user must not be a superuser"
        assert row["rolbypassrls"] is False, "app_user must not bypass RLS"
