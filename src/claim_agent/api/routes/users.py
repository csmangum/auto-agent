"""Admin-only user management."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError

from claim_agent.api.auth import AuthContext
from claim_agent.rbac_roles import KNOWN_ROLES
from claim_agent.api.deps import require_role
from claim_agent.db.user_repository import MIN_PASSWORD_LENGTH, UserRepository

router = APIRouter(prefix="/users", tags=["users"])

RequireAdmin = require_role("admin")


class UserCreateBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)
    role: str = Field(..., description="One of: adjuster, supervisor, admin, executive")


class UserUpdateBody(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=MIN_PASSWORD_LENGTH)
    role: Optional[str] = None
    is_active: Optional[bool] = None


def _public_user(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k != "password_hash"}


@router.get("")
def list_users(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _auth: AuthContext = RequireAdmin,
):
    repo = UserRepository()
    users = repo.list_users(limit=limit, offset=offset)
    total = repo.count_users()
    return {"users": [_public_user(u) for u in users], "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201)
def create_user(body: UserCreateBody, _auth: AuthContext = RequireAdmin):
    if body.role not in KNOWN_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(KNOWN_ROLES)}")
    repo = UserRepository()
    try:
        u = repo.create_user(body.email, body.password, body.role)
    except ValueError as e:
        msg = str(e).lower()
        if "already" in msg:
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _public_user(u)


@router.get("/{user_id}")
def get_user(user_id: str, _auth: AuthContext = RequireAdmin):
    repo = UserRepository()
    u = repo.get_user_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _public_user(u)


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdateBody, _auth: AuthContext = RequireAdmin):
    if body.role is not None and body.role not in KNOWN_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(KNOWN_ROLES)}")
    repo = UserRepository()
    if repo.get_user_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        u = repo.update_user(
            user_id,
            email=body.email,
            role=body.role,
            is_active=body.is_active,
            password=body.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="Email already in use") from e
    assert u is not None
    return _public_user(u)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, _auth: AuthContext = RequireAdmin) -> Response:
    repo = UserRepository()
    if not repo.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return Response(status_code=204)
