"""Dependencies for repair shop portal (X-Repair-Shop-Access-Token or Bearer JWT)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import jwt as pyjwt
from fastapi import HTTPException, Request

from claim_agent.config import get_settings
from claim_agent.config.settings import get_jwt_secret
from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository
from claim_agent.services.repair_shop_portal_tokens import verify_repair_shop_token

logger = logging.getLogger(__name__)


@dataclass
class RepairShopPortalContext:
    claim_id: str
    shop_id: str | None
    identity: str


@dataclass
class RepairShopJWTContext:
    """Auth context for shop-user JWT (multi-claim endpoints)."""

    shop_user_id: str
    shop_id: str
    identity: str


def _verify_shop_jwt(token: str) -> dict[str, Any] | None:
    """Verify a JWT issued to a shop user. Returns decoded payload or None.

    In addition to cryptographic verification and claim checks, this looks up
    the user record and rejects deactivated accounts so that a deactivation
    takes effect immediately rather than waiting for JWT expiry.
    """
    secret = get_jwt_secret()
    if not secret:
        return None
    try:
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("token_use") == "refresh":
            return None
        if payload.get("role") != "shop_user":
            return None
        if not payload.get("shop_id"):
            return None
        if not payload.get("sub"):
            return None
        user = RepairShopUserRepository().get_shop_user_by_id(str(payload["sub"]))
        if user is None or not user.get("is_active"):
            return None
        return payload
    except Exception:
        logger.debug("Shop user JWT decode/validation failed", exc_info=True)
        return None


def require_shop_user_jwt(request: Request) -> RepairShopJWTContext:
    """Require a valid shop-user JWT (Bearer token). Used by multi-claim endpoints."""
    if not get_settings().repair_shop_portal.enabled:
        raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
    bearer = request.headers.get("authorization", "")
    if not bearer.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Bearer token required. Authenticate via POST /api/repair-portal/auth/login.",
        )
    token = bearer[7:].strip()
    payload = _verify_shop_jwt(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return RepairShopJWTContext(
        shop_user_id=str(payload["sub"]),
        shop_id=str(payload["shop_id"]),
        identity=f"shop-user:{payload['sub']}",
    )


def require_repair_shop_access(request: Request, claim_id: str) -> RepairShopPortalContext:
    """Authenticate a repair shop for a specific claim.

    Accepts two credential types (in precedence order):

    1. **Shop-user JWT** (``Authorization: Bearer <jwt>``) – when the bearer
       token verifies as a shop-user JWT, issued by
       ``POST /api/repair-portal/auth/login``. The claim must be assigned to
       that shop. A non-shop Bearer (e.g. another API key) does not block the
       legacy header below.

    2. **Per-claim token** (``X-Repair-Shop-Access-Token``) – legacy single-use
       magic token minted by adjusters; kept for backward compatibility.
    """
    if not get_settings().repair_shop_portal.enabled:
        raise HTTPException(status_code=503, detail="Repair shop portal is disabled")

    # --- JWT path (shop user account) ---
    # Only treat Bearer as shop JWT when verification succeeds; otherwise fall
    # through so a random/other API Bearer plus X-Repair-Shop-Access-Token still works.
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
        payload = _verify_shop_jwt(token)
        if payload is not None:
            shop_id = str(payload["shop_id"])
            sub = str(payload["sub"])
            repo = RepairShopUserRepository()
            if not repo.is_claim_assigned_to_shop(claim_id, shop_id):
                raise HTTPException(
                    status_code=403,
                    detail="This claim is not assigned to your shop",
                )
            return RepairShopPortalContext(
                claim_id=claim_id,
                shop_id=shop_id,
                identity=f"shop-user:{sub}",
            )

    # --- Per-claim token path (legacy) ---
    raw = request.headers.get("x-repair-shop-access-token")
    if not raw or not str(raw).strip():
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access. Provide X-Repair-Shop-Access-Token.",
        )
    rec = verify_repair_shop_token(claim_id, str(raw).strip())
    if rec is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access. Provide X-Repair-Shop-Access-Token.",
        )
    ident = rec.shop_id or f"repair-portal-token:{rec.token_id}"
    return RepairShopPortalContext(claim_id=rec.claim_id, shop_id=rec.shop_id, identity=ident)

