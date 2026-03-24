"""Admin endpoints for repair shop user account management."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.db.repair_shop_user_repository import MIN_PASSWORD_LENGTH, RepairShopUserRepository

router = APIRouter(prefix="/repair-shop-users", tags=["repair-shop-users"])

RequireAdmin = require_role("admin")


class ShopUserCreateBody(BaseModel):
    shop_id: str = Field(..., min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)


@router.get("")
def list_shop_users(
    shop_id: Optional[str] = Query(default=None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth: AuthContext = RequireAdmin,
):
    """List repair shop user accounts (admin only)."""
    repo = RepairShopUserRepository()
    users = repo.list_shop_users(shop_id=shop_id, limit=limit, offset=offset)
    return {"users": users, "total": len(users)}


@router.post("", status_code=201)
def create_shop_user(body: ShopUserCreateBody, _auth: AuthContext = RequireAdmin):
    """Create a repair shop user account (admin only)."""
    repo = RepairShopUserRepository()
    try:
        user = repo.create_shop_user(
            shop_id=body.shop_id,
            email=body.email,
            password=body.password,
        )
    except ValueError as e:
        msg = str(e).lower()
        if "already" in msg:
            raise HTTPException(status_code=409, detail=str(e)) from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    return user


@router.get("/{user_id}")
def get_shop_user(user_id: str, _auth: AuthContext = RequireAdmin):
    """Get a repair shop user by ID (admin only)."""
    repo = RepairShopUserRepository()
    user = repo.get_shop_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Shop user not found")
    return user


@router.delete("/{user_id}", status_code=204)
def deactivate_shop_user(user_id: str, _auth: AuthContext = RequireAdmin):
    """Deactivate a repair shop user account (admin only)."""
    from fastapi import Response

    repo = RepairShopUserRepository()
    found = repo.deactivate_shop_user(user_id)
    if not found:
        raise HTTPException(status_code=404, detail="Shop user not found")
    return Response(status_code=204)
