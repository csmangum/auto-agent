"""Dependencies for third-party portal (X-Third-Party-Access-Token)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from claim_agent.config import get_settings
from claim_agent.services.third_party_portal_tokens import verify_third_party_token


@dataclass
class ThirdPartyPortalContext:
    claim_id: str
    party_id: int | None
    identity: str


def require_third_party_portal_access(
    request: Request, claim_id: str
) -> ThirdPartyPortalContext:
    if not get_settings().third_party_portal.enabled:
        raise HTTPException(status_code=503, detail="Third-party portal is disabled")
    raw = request.headers.get("x-third-party-access-token")
    if not raw or not str(raw).strip():
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access. Provide X-Third-Party-Access-Token.",
        )
    rec = verify_third_party_token(claim_id, str(raw).strip())
    if rec is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access. Provide X-Third-Party-Access-Token.",
        )
    ident = (
        f"third-party-party:{rec.party_id}"
        if rec.party_id is not None
        else f"third-party-portal-token:{rec.token_id}"
    )
    return ThirdPartyPortalContext(
        claim_id=rec.claim_id, party_id=rec.party_id, identity=ident
    )
