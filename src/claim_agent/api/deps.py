"""FastAPI dependencies for auth, RBAC, and database connections."""

import logging
from collections.abc import AsyncGenerator
from typing import cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from claim_agent.api.auth import AuthContext, is_auth_required

logger = logging.getLogger(__name__)

_auth_warning_logged = False


def get_auth(request: Request) -> AuthContext | None:
    """Extract auth from request. If auth required and missing, raise 401.
    Middleware already verified and set request.state.auth for /api/* paths."""
    if not is_auth_required():
        return None

    auth = getattr(request.state, "auth", None)
    if auth is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return cast(AuthContext, auth)


def require_role(*roles: str):
    """Dependency that requires one of the given roles. Raises 403 if insufficient."""

    def _check(request: Request) -> AuthContext:
        from fastapi import HTTPException

        if not is_auth_required():
            global _auth_warning_logged
            if not _auth_warning_logged:
                logger.warning(
                    "No API_KEYS, CLAIMS_API_KEY, or JWT_SECRET configured. "
                    "All endpoints are accessible without authentication. "
                    "Set at least one auth variable for production deployments."
                )
                _auth_warning_logged = True
            return AuthContext(identity="anonymous", role="admin")

        auth = get_auth(request)
        assert auth is not None
        if auth.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required role: one of {roles}",
            )
        return auth

    return Depends(_check)


RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")
RequireSupervisor = require_role("supervisor", "admin", "executive")


async def get_async_db() -> AsyncGenerator[AsyncConnection, None]:
    """FastAPI dependency that yields an async SQLAlchemy connection (PostgreSQL only).

    Use as a route dependency when the PostgreSQL backend is active and
    non-blocking database I/O is desired::

        @router.get("/example")
        async def example(conn: AsyncConnection = Depends(get_async_db)):
            result = await conn.execute(text("SELECT 1"))

    Raises:
        RuntimeError: If the active backend is SQLite (DATABASE_URL not set).
    """
    from claim_agent.db.database import get_connection_async

    async with get_connection_async() as conn:
        yield conn
