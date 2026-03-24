"""Shared JWT helpers for repair-shop user authentication.

Used by both ``repair_portal`` and ``unified_portal`` route modules to avoid
duplicating the JWT encoding logic and the login request model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field

from claim_agent.config.settings import get_jwt_access_ttl_seconds, get_jwt_secret


class ShopLoginBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


def encode_shop_access_token(user_id: str, shop_id: str) -> str:
    """Issue a short-lived JWT for a repair shop user.

    Raises ``HTTPException(503)`` when ``JWT_SECRET`` is not configured.
    """
    secret = get_jwt_secret()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="JWT_SECRET is not configured; cannot issue access tokens",
        )
    ttl = get_jwt_access_ttl_seconds()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": "shop_user",
        "shop_id": shop_id,
        "token_use": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")
