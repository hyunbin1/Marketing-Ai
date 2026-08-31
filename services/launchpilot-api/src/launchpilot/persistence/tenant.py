"""Request-scoped tenant context.

The active workspace for the current request is held in a ContextVar so that the
database layer can stamp it onto every connection as the `app.workspace_id` GUC,
which the Row-Level Security policies read to filter rows. Setting the context is
the bridge between "the app knows the tenant" and "the database enforces it".

Auth/scope resolution runs BEFORE the context is set (it must, to discover which
workspace a campaign belongs to) and therefore uses the admin connection that
bypasses RLS. Only domain reads/writes run inside `tenant_context`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_current_workspace_id: ContextVar[str | None] = ContextVar(
    "app_current_workspace_id", default=None
)


def current_workspace_id() -> str | None:
    """Return the workspace bound to the current request, or None outside one."""
    return _current_workspace_id.get()


@contextmanager
def tenant_context(workspace_id: UUID | str) -> Iterator[None]:
    """Bind a workspace to the current context for the duration of the block.

    Every database connection opened while this is active stamps the workspace as
    the `app.workspace_id` GUC, so RLS returns only that tenant's rows.
    """
    token = _current_workspace_id.set(str(workspace_id))
    try:
        yield
    finally:
        _current_workspace_id.reset(token)
