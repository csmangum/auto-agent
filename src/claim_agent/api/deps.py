"""FastAPI dependencies for auth and RBAC."""

from fastapi import Depends, Request

from claim_agent.api.auth import AuthContext, is_auth_required, verify_token


def _get_token(request: Request) -> str | None:
    """Extract token from X-API-Key or Authorization: Bearer."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return api_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_auth(request: Request) -> AuthContext | None:
    """Extract auth from request. If auth required and missing, raise 401.
    Middleware already verified and set request.state.auth for /api/* paths."""
    if not is_auth_required():
        return None

    auth = getattr(request.state, "auth", None)
    if auth is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return auth


def require_role(*roles: str):
    """Dependency that requires one of the given roles. Raises 403 if insufficient."""

    def _check(request: Request) -> AuthContext:
        from fastapi import HTTPException

        if not is_auth_required():
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
