"""FastAPI dependencies for claimant portal authentication."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from claim_agent.config import get_settings
from claim_agent.services.portal_verification import (
    ClaimantContext,
    get_claim_ids_for_claimant,
)


@dataclass
class PortalSession:
    """Verified portal session with claim IDs the claimant can access."""

    claim_ids: list[str]
    token: str | None
    policy_number: str | None
    vin: str | None
    email: str | None


def _extract_portal_headers(request: Request) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Extract verification headers from request. Use lowercase for Starlette compatibility."""
    token = request.headers.get("x-claim-access-token")
    cid = request.headers.get("x-claim-id")
    pn = request.headers.get("x-policy-number")
    vin = request.headers.get("x-vin")
    email = request.headers.get("x-email")
    return (
        token.strip() if token else None,
        cid.strip() if cid else None,
        pn.strip() if pn else None,
        vin.strip() if vin else None,
        email.strip() if email else None,
    )


async def require_portal_session(request: Request) -> PortalSession:
    """Dependency: verify claimant and return session with claim_ids. Raises 401 if invalid."""
    settings = get_settings()
    if not settings.portal.enabled:
        raise HTTPException(status_code=503, detail="Claimant portal is disabled")

    token, _cid, pn, vin, email = _extract_portal_headers(request)

    claim_ids = get_claim_ids_for_claimant(
        token=token,
        policy_number=pn,
        vin=vin,
        email=email,
    )

    if not claim_ids:
        mode = settings.portal.verification_mode
        if mode == "token":
            detail = "Invalid or expired access. Provide a valid claim access token."
        elif mode == "email":
            detail = "Invalid or expired access. Provide your email address."
        else:
            detail = "Invalid or expired access. Provide your policy number and VIN."
        raise HTTPException(status_code=401, detail=detail)

    return PortalSession(
        claim_ids=claim_ids,
        token=token,
        policy_number=pn,
        vin=vin,
        email=email,
    )


async def require_claimant_access(
    claim_id: str,
    session: PortalSession = Depends(require_portal_session),
) -> ClaimantContext:
    """Dependency: verify claimant has access to the given claim_id. Raises 404 if not."""
    if claim_id not in session.claim_ids:
        raise HTTPException(status_code=404, detail="Claim not found")
    identity = (
        session.email
        or (session.policy_number and f"policy:{session.policy_number[:4]}***")
        or "portal-claimant"
    )
    return ClaimantContext(claim_id=claim_id, identity=str(identity))
