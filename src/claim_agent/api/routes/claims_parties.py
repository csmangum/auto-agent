"""Party management and portal token routes for claims."""

from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import require_role
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.config import get_settings
from claim_agent.context import ClaimContext
from claim_agent.db.constants import THIRD_PARTY_PORTAL_ELIGIBLE_PARTY_TYPES
from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository
from claim_agent.exceptions import DomainValidationError
from claim_agent.models.party import PartyRelationshipType
from claim_agent.services.portal_verification import create_claim_access_token
from claim_agent.services.repair_shop_portal_tokens import create_repair_shop_access_token
from claim_agent.services.third_party_portal_tokens import create_third_party_access_token
from claim_agent.api.routes._claims_helpers import get_claim_context

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PartyConsentUpdate(BaseModel):
    """Request body for PATCH /claims/{claim_id}/parties/{party_id}/consent."""

    consent_status: Literal["pending", "granted", "revoked"] = Field(
        ...,
        description="Data processing consent status. Revoked excludes party PII from LLM prompts.",
    )


class CreatePartyRelationshipBody(BaseModel):
    """Request body for POST /claims/{claim_id}/party-relationships."""

    from_party_id: int = Field(..., ge=1, description="Subject party (edge tail)")
    to_party_id: int = Field(..., ge=1, description="Related party (edge head)")
    relationship_type: PartyRelationshipType = Field(..., description="Directed relationship type")


class CreatePortalTokenBody(BaseModel):
    """Optional party or email for the portal token."""

    party_id: Optional[int] = Field(None, description="Claim party ID (claimant/policyholder)")
    email: Optional[str] = Field(None, description="Email to associate with token")


class CreateRepairShopPortalTokenBody(BaseModel):
    """Optional shop identifier stored with the token (audit / repair_status.shop_id)."""

    shop_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Repair shop id or code; used when posting repair status if set",
    )


class CreateThirdPartyPortalTokenBody(BaseModel):
    """Claim party to associate with the token (required for audit and eligibility)."""

    party_id: int = Field(
        ...,
        description=(
            "Claim party ID on this claim; must be witness, attorney, provider, or lienholder"
        ),
    )


class AssignRepairShopBody(BaseModel):
    shop_id: str = Field(..., min_length=1, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.patch("/claims/{claim_id}/parties/{party_id}/consent", dependencies=[RequireAdjuster])
def update_party_consent(
    claim_id: str,
    party_id: int,
    body: PartyConsentUpdate,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update data processing consent for a claim party. Revoked excludes party PII from LLM."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    parties = ctx.repo.get_claim_parties(claim_id)
    if not any(p.get("id") == party_id for p in parties):
        raise HTTPException(status_code=404, detail="Party not found")
    ctx.repo.update_claim_party(party_id, {"consent_status": body.consent_status})
    return {"claim_id": claim_id, "party_id": party_id, "consent_status": body.consent_status}


@router.post(
    "/claims/{claim_id}/party-relationships",
    dependencies=[RequireAdjuster],
    status_code=201,
)
def create_party_relationship(
    claim_id: str,
    body: CreatePartyRelationshipBody,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a directed party-to-party link (e.g. claimant represented_by attorney)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        rel_id = ctx.repo.add_claim_party_relationship(
            claim_id,
            body.from_party_id,
            body.to_party_id,
            body.relationship_type,
        )
    except DomainValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "id": rel_id,
        "claim_id": claim_id,
        "from_party_id": body.from_party_id,
        "to_party_id": body.to_party_id,
        "relationship_type": body.relationship_type,
    }


@router.delete(
    "/claims/{claim_id}/party-relationships/{relationship_id}",
    dependencies=[RequireAdjuster],
    status_code=204,
)
def delete_party_relationship(
    claim_id: str,
    relationship_id: int,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Remove a party-to-party link for this claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    deleted = ctx.repo.delete_claim_party_relationship(claim_id, relationship_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Party relationship not found")


@router.post("/claims/{claim_id}/portal-token", dependencies=[RequireAdjuster])
def create_portal_token(
    request: Request,
    claim_id: str,
    body: CreatePortalTokenBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a claim access token for the claimant portal. Returns the raw token (send to claimant once)."""
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
        if not get_settings().portal.enabled:
            raise HTTPException(status_code=503, detail="Claimant portal is disabled")
        email = body.email
        party_id = body.party_id
        if not email and party_id:
            parties = ctx.repo.get_claim_parties(claim_id)
            for p in parties:
                if p.get("id") == party_id:
                    email = p.get("email")
                    break
        if not email and not party_id:
            parties = ctx.repo.get_claim_parties(claim_id)
            for p in parties:
                if p.get("party_type") in ("claimant", "policyholder") and p.get("email"):
                    email = p.get("email")
                    party_id = p.get("id")
                    break
        token = create_claim_access_token(claim_id, party_id=party_id, email=email)
        result = {"claim_id": claim_id, "token": token}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post("/claims/{claim_id}/repair-shop-portal-token", dependencies=[RequireAdjuster])
def create_repair_shop_portal_token(
    request: Request,
    claim_id: str,
    body: CreateRepairShopPortalTokenBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a repair shop access token for this claim. Returns the raw token once."""
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached
    try:
        claim_row = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
        if claim_row.get("claim_type") != "partial_loss":
            raise HTTPException(
                status_code=400,
                detail="Repair shop portal tokens are only issued for partial_loss claims",
            )
        if not get_settings().repair_shop_portal.enabled:
            raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
        token = create_repair_shop_access_token(
            claim_id,
            shop_id=body.shop_id,
        )
        result = {"claim_id": claim_id, "token": token}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post(
    "/claims/{claim_id}/repair-shop-assignment",
    dependencies=[RequireAdjuster],
    status_code=201,
)
def assign_repair_shop_to_claim(
    claim_id: str,
    body: AssignRepairShopBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Assign a repair shop to a claim so shop users can view it via the multi-claim portal."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    repo = RepairShopUserRepository()
    try:
        assignment = repo.assign_claim_to_shop(
            claim_id=claim_id,
            shop_id=body.shop_id,
            assigned_by=auth.identity,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return assignment


@router.get("/claims/{claim_id}/repair-shop-assignments", dependencies=[RequireAdjuster])
def list_repair_shop_assignments(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List all repair shop assignments for a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    repo = RepairShopUserRepository()
    return {"claim_id": claim_id, "assignments": repo.get_assignments_for_claim(claim_id)}


@router.delete(
    "/claims/{claim_id}/repair-shop-assignment/{shop_id}",
    dependencies=[RequireAdjuster],
)
def remove_repair_shop_assignment(
    claim_id: str,
    shop_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Remove a repair shop assignment from a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    repo = RepairShopUserRepository()
    found = repo.remove_assignment(claim_id, shop_id)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Shop '{shop_id}' is not assigned to claim '{claim_id}'",
        )
    return {"ok": True}


@router.post("/claims/{claim_id}/third-party-portal-token", dependencies=[RequireAdjuster])
def create_third_party_portal_token(
    request: Request,
    claim_id: str,
    body: CreateThirdPartyPortalTokenBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a third-party portal access token. Returns the raw token once."""
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached
    try:
        ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
        if not get_settings().third_party_portal.enabled:
            raise HTTPException(status_code=503, detail="Third-party portal is disabled")
        party_id = body.party_id
        parties = ctx.repo.get_claim_parties(claim_id)
        match = next((p for p in parties if p.get("id") == party_id), None)
        if match is None:
            raise HTTPException(
                status_code=400,
                detail=f"party_id {party_id} is not a party on this claim",
            )
        ptype = str(match.get("party_type") or "").strip().lower()
        if ptype not in THIRD_PARTY_PORTAL_ELIGIBLE_PARTY_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Third-party portal tokens may only be issued for parties of type: "
                    f"{', '.join(sorted(THIRD_PARTY_PORTAL_ELIGIBLE_PARTY_TYPES))}"
                ),
            )
        token = create_third_party_access_token(claim_id, party_id=party_id)
        result = {"claim_id": claim_id, "token": token}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise
