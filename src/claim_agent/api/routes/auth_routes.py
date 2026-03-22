"""Email/password login and refresh token exchange."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from claim_agent.config.settings import (
    get_jwt_access_ttl_seconds,
    get_jwt_refresh_ttl_seconds,
    get_jwt_secret,
)
from claim_agent.db.user_repository import UserRepository, hash_refresh_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class RefreshBody(BaseModel):
    refresh_token: str = Field(..., min_length=1)


def _encode_access_token(sub: str, role: str) -> str:
    secret = get_jwt_secret()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="JWT_SECRET is not configured; cannot issue access tokens",
        )
    ttl = get_jwt_access_ttl_seconds()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "token_use": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


@router.post("/login")
def login(body: LoginBody):
    """Authenticate with email and password; returns access (JWT) and refresh (opaque) tokens."""
    repo = UserRepository()
    user = repo.verify_user_password(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = _encode_access_token(str(user["id"]), str(user["role"]))
    ttl = get_jwt_refresh_ttl_seconds()
    raw_refresh, _tid = repo.issue_refresh_token(str(user["id"]), ttl)
    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": get_jwt_access_ttl_seconds(),
    }


@router.post("/refresh")
def refresh(body: RefreshBody):
    """Exchange a valid refresh token for new access and refresh tokens (rotation)."""
    repo = UserRepository()
    th = hash_refresh_token(body.refresh_token.strip())
    row = repo.get_refresh_token_row_by_hash(th)
    if row is None or not repo.is_refresh_token_valid(row):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user_id = str(row["user_id"])
    user = repo.get_user_by_id(user_id)
    if user is None or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    old_id = str(row["id"])
    access = _encode_access_token(user_id, str(user["role"]))
    ttl = get_jwt_refresh_ttl_seconds()
    raw_refresh, _new_id = repo.rotate_refresh_token(old_id, user_id, ttl)
    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": get_jwt_access_ttl_seconds(),
    }
