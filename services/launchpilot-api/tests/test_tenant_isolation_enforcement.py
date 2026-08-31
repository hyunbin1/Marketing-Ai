"""Behavioural verification that RLS scopes rows to the request's workspace (Step 1b).

Requires PostgreSQL (`docker compose up -d postgres`). Seeds two workspaces as the
admin/superuser (which bypasses RLS), then reads as the non-superuser app_user role
under different tenant contexts and asserts each sees only its own rows, and none
when no context is set (fail-closed).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Json

from launchpilot.persistence.postgres import PostgresDatabase
from launchpilot.persistence.tenant import tenant_context

APP_PASSWORD = "app-user-test"


def _app_user_url(admin_url: str) -> str:
    parts = urlsplit(admin_url)
    netloc = f"app_user:{APP_PASSWORD}@{parts.hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _seed_two_tenants(admin: PostgresDatabase):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    ids = {
        "ws_a": uuid4(), "ws_b": uuid4(),
        "camp_a": uuid4(), "camp_b": uuid4(),
        "doc_a": uuid4(), "doc_b": uuid4(),
    }
    with admin.connect() as connection:
        # Ensure the runtime role can log in even on a volume where the init
        # script did not run.
        connection.execute(f"ALTER ROLE app_user LOGIN PASSWORD '{APP_PASSWORD}'")
        for key in ("ws_a", "ws_b"):
            connection.execute(
                "INSERT INTO workspaces(id, name, created_at) VALUES (%s, %s, %s)",
                (ids[key], f"workspace-{key}", now),
            )
        for camp, ws in (("camp_a", "ws_a"), ("camp_b", "ws_b")):
            connection.execute(
                """INSERT INTO campaigns(
                    id, workspace_id, name, goal, period_start, period_end,
                    target_metrics, resource_bindings, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    ids[camp], ids[ws], "campaign", "goal",
                    date(2026, 1, 1), date(2026, 1, 31),
                    Json([]), Json({}), now,
                ),
            )
        for doc, camp, ws in (("doc_a", "camp_a", "ws_a"), ("doc_b", "camp_b", "ws_b")):
            connection.execute(
                """INSERT INTO campaign_documents(
                    id, campaign_id, workspace_id, document_type, title, content,
                    source_ref, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (ids[doc], ids[camp], ids[ws], "MEMO", "title", "body", f"src-{doc}", now),
            )
    return ids


def _campaign_ids(app: PostgresDatabase) -> set:
    with app.connect() as connection:
        return {row["id"] for row in connection.execute("SELECT id FROM campaigns").fetchall()}


def _document_ids(app: PostgresDatabase) -> set:
    with app.connect() as connection:
        return {
            row["id"]
            for row in connection.execute("SELECT id FROM campaign_documents").fetchall()
        }


def test_rls_scopes_rows_to_the_active_workspace(postgres_database) -> None:
    ids = _seed_two_tenants(postgres_database)
    app = PostgresDatabase(
        _app_user_url(postgres_database.database_url),
        set_tenant_guc=True,
        run_migrations=False,
    )

    with tenant_context(ids["ws_a"]):
        assert _campaign_ids(app) == {ids["camp_a"]}
        assert _document_ids(app) == {ids["doc_a"]}

    with tenant_context(ids["ws_b"]):
        assert _campaign_ids(app) == {ids["camp_b"]}
        assert _document_ids(app) == {ids["doc_b"]}


def test_rls_returns_nothing_without_a_tenant_context(postgres_database) -> None:
    _seed_two_tenants(postgres_database)
    app = PostgresDatabase(
        _app_user_url(postgres_database.database_url),
        set_tenant_guc=True,
        run_migrations=False,
    )

    # No tenant_context: the GUC is unset, so the policy matches no rows (fail-closed).
    assert _campaign_ids(app) == set()
    assert _document_ids(app) == set()


def test_writes_are_constrained_to_the_active_workspace(postgres_database) -> None:
    ids = _seed_two_tenants(postgres_database)
    app = PostgresDatabase(
        _app_user_url(postgres_database.database_url),
        set_tenant_guc=True,
        run_migrations=False,
    )
    now = datetime(2026, 2, 1, tzinfo=UTC)

    # Writing a row for workspace B while scoped to workspace A must be rejected by
    # the WITH CHECK clause.
    with (
        tenant_context(ids["ws_a"]),
        pytest.raises(psycopg.errors.Error),
        app.connect() as connection,
    ):
        connection.execute(
            """INSERT INTO campaign_documents(
                id, campaign_id, workspace_id, document_type, title, content,
                source_ref, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                uuid4(), ids["camp_b"], ids["ws_b"], "MEMO",
                "cross", "tenant", "src-cross", now,
            ),
        )
