"""Unified external-portal routes.

This module adds a small set of routes under the existing ``/portal`` prefix
that serve the *unified* login flow shared by all external portal roles:

- ``GET  /portal/auth/role``   – Detect caller's role from any credential type.
- ``POST /portal/auth/login``  – Repair-shop user login (mirrors
  ``POST /repair-portal/auth/login`` so the frontend has a single entry point).

These endpoints are intentionally mounted on the ``/portal`` prefix so they
fall inside the existing auth-middleware bypass (``/api/portal/*`` is already
public; per-endpoint authorisation is handled by the dependency layer).

Deprecation
-----------
``/api/repair-portal/auth/login`` remains functional for backward compatibility.
New integrations should prefer ``POST /api/portal/auth/login``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from claim_agent.api.unified_portal_deps import (
    UnifiedPortalSession,
    require_unified_portal_session,
)
from claim_agent.config import get_settings
from claim_agent.config.settings import get_jwt_access_ttl_seconds
from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository
from claim_agent.services.shop_jwt import ShopLoginBody, encode_shop_access_token
from claim_agent.services.unified_portal_tokens import (
    VALID_PORTAL_SCOPES,
    create_unified_portal_token,
)

router = APIRouter(prefix="/portal", tags=["unified-portal"])


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------


@router.get("/auth/role")
def detect_portal_role(
    session: UnifiedPortalSession = Depends(require_unified_portal_session),
):
    """Return the caller's portal role resolved from the presented credential.

    Accepts the same credential headers as the full portal endpoints:

    - ``X-Portal-Token``              – unified token (role embedded)
    - ``X-Repair-Shop-Access-Token``  – legacy per-claim shop token (+ ``X-Claim-Id``)
    - ``X-Claim-Access-Token``        – legacy claimant token
    - ``X-Policy-Number`` + ``X-Vin`` – policy/VIN claimant lookup
    - ``X-Email``                     – email claimant lookup (when verification disabled)

    **Returns** ``{"role": "claimant"|"repair_shop"|"tpa", "claim_ids": [...], "redirect": "…"}``

    The ``redirect`` field is a suggested frontend path based on the resolved role.

    Security note
    -------------
    When legacy token headers are used, the backend probes the appropriate
    token table directly (no cross-table sequential search), so there is no
    timing oracle across token types.  However, sequential probing of
    ``repair_shop_access_tokens`` vs ``claim_access_tokens`` within the legacy
    path could leak information via response latency.  New deployments should
    issue unified tokens (``X-Portal-Token``) which carry the role explicitly.
    """
    if session.role == "claimant":
        redirect = "/portal/claims"
    elif session.role == "tpa":
        redirect = "/third-party-portal/claims"
    else:
        redirect = "/repair-portal/claims"
    return {
        "role": session.role,
        "claim_ids": session.claim_ids,
        "shop_id": session.shop_id,
        "scopes": session.scopes,
        "redirect": redirect,
    }


# ---------------------------------------------------------------------------
# Unified repair-shop user login
# ---------------------------------------------------------------------------


@router.post("/auth/login")
def unified_shop_login(body: ShopLoginBody):
    """Authenticate a repair-shop user; returns a JWT access token.

    Mirrors ``POST /api/repair-portal/auth/login`` so the frontend can use a
    **single** login endpoint regardless of portal role.  The ``role`` field
    in the response tells the client where to redirect after login.

    This endpoint requires the repair-shop portal to be enabled
    (``REPAIR_SHOP_PORTAL_ENABLED=true``).
    """
    if not get_settings().repair_shop_portal.enabled:
        raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
    repo = RepairShopUserRepository()
    user = repo.verify_shop_user_password(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = encode_shop_access_token(str(user["id"]), str(user["shop_id"]))
    return {
        "access_token": access,
        "token_type": "bearer",
        "role": "repair_shop",
        "expires_in": get_jwt_access_ttl_seconds(),
        "shop_id": user["shop_id"],
        "redirect": "/repair-portal/claims",
    }


# ---------------------------------------------------------------------------
# Unified token issuance (internal / adjuster use via API key auth)
# ---------------------------------------------------------------------------


class IssueUnifiedTokenBody(BaseModel):
    role: Literal["claimant", "repair_shop", "tpa"]
    scopes: list[str] = Field(default_factory=list)
    claim_id: str | None = Field(default=None)
    shop_id: str | None = Field(default=None)

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v: list[str]) -> list[str]:
        invalid = set(v) - VALID_PORTAL_SCOPES
        if invalid:
            raise ValueError(f"Invalid scopes: {sorted(invalid)}")
        return v


@router.post("/auth/issue-token")
def issue_unified_portal_token(body: IssueUnifiedTokenBody):
    """Issue a unified portal token for a given role.

    This endpoint is intended for **internal / adjuster use** and is protected
    by the standard API-key / Bearer-token auth middleware (unlike the rest of
    ``/portal/*`` which is public).  Frontends or scripts can obtain a token
    here and deliver it to the external party via email or secure link.

    Returns the raw token once -- not stored in plaintext.
    """
    raw = create_unified_portal_token(
        body.role,
        scopes=body.scopes,
        claim_id=body.claim_id,
        shop_id=body.shop_id,
    )
    return {
        "token": raw,
        "role": body.role,
        "claim_id": body.claim_id,
        "shop_id": body.shop_id,
        "scopes": body.scopes,
    }
