"""Dependencies for repair shop portal (X-Repair-Shop-Access-Token)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from claim_agent.config import get_settings
from claim_agent.services.repair_shop_portal_tokens import verify_repair_shop_token


@dataclass
class RepairShopPortalContext:
    claim_id: str
    shop_id: str | None
    identity: str


def require_repair_shop_access(request: Request, claim_id: str) -> RepairShopPortalContext:
    if not get_settings().repair_shop_portal.enabled:
        raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
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
    ident = rec.shop_id or "repair-shop-token"
    return RepairShopPortalContext(claim_id=rec.claim_id, shop_id=rec.shop_id, identity=ident)
