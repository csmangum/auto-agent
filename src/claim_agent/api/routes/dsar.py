"""DSAR (Data Subject Access Request) API routes for privacy compliance."""

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.services.dsar import (
    fulfill_access_request,
    fulfill_deletion_request,
    get_dsar_request,
    list_dsar_requests,
    revoke_consent_by_email,
    submit_access_request,
    submit_deletion_request,
)

router = APIRouter(prefix="/dsar", tags=["dsar"])


class AccessRequestInput(BaseModel):
    """Request body for POST /dsar/access."""

    claimant_identifier: str = Field(..., description="Email or identifier for the claimant")
    claim_id: Optional[str] = Field(None, description="Claim ID for verification")
    policy_number: Optional[str] = Field(None, description="Policy number for verification")
    vin: Optional[str] = Field(None, description="VIN for verification")


@router.post("/access")
async def dsar_submit_access(
    body: AccessRequestInput = Body(...),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Submit a DSAR access request. Requires claimant verification data.

    Provide either claim_id, or policy_number+vin to verify the claimant.
    """
    verification_data: dict[str, Any] = {}
    if body.claim_id:
        verification_data["claim_id"] = body.claim_id
    if body.policy_number:
        verification_data["policy_number"] = body.policy_number
    if body.vin:
        verification_data["vin"] = body.vin
    if not verification_data:
        raise HTTPException(
            status_code=400,
            detail="Provide either claim_id or (policy_number and vin) for verification",
        )
    request_id = submit_access_request(
        claimant_identifier=body.claimant_identifier,
        verification_data=verification_data,
        actor_id=getattr(_auth, "actor_id", None) or "api",
    )
    return {"request_id": request_id, "status": "pending"}


@router.get("/requests/{request_id}")
async def dsar_get_request(
    request_id: str,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Get DSAR request status by request_id."""
    req = get_dsar_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="DSAR request not found")
    return req


@router.get("/requests")
async def dsar_list_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    request_type: Optional[str] = Query(None, description="Filter by request_type (access|deletion)"),
    limit: int = Query(100, ge=1, le=1000, description="Max items to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """List DSAR requests, optionally filtered by status and/or request_type. Paginated."""
    items, total = list_dsar_requests(
        status=status, request_type=request_type, limit=limit, offset=offset
    )
    return {"requests": items, "total": total, "limit": limit, "offset": offset}


class ConsentRevokeInput(BaseModel):
    """Request body for POST /dsar/consent-revoke."""

    email: str = Field(..., description="Claimant email to revoke consent for")


class DeletionRequestInput(BaseModel):
    """Request body for POST /dsar/deletion."""

    claimant_identifier: str = Field(..., description="Email or identifier for the claimant")
    claim_id: Optional[str] = Field(None, description="Claim ID for verification")
    policy_number: Optional[str] = Field(None, description="Policy number for verification")
    vin: Optional[str] = Field(None, description="VIN for verification")


@router.post("/deletion")
async def dsar_submit_deletion(
    body: DeletionRequestInput = Body(...),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Submit a DSAR deletion request (right-to-delete)."""
    verification_data: dict[str, Any] = {}
    if body.claim_id:
        verification_data["claim_id"] = body.claim_id
    if body.policy_number:
        verification_data["policy_number"] = body.policy_number
    if body.vin:
        verification_data["vin"] = body.vin
    if not verification_data:
        raise HTTPException(
            status_code=400,
            detail="Provide either claim_id or (policy_number and vin) for verification",
        )
    request_id = submit_deletion_request(
        claimant_identifier=body.claimant_identifier,
        verification_data=verification_data,
        actor_id=getattr(_auth, "actor_id", None) or "api",
    )
    return {"request_id": request_id, "status": "pending"}


@router.post("/deletion/fulfill/{request_id}")
async def dsar_fulfill_deletion(
    request_id: str,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Fulfill a deletion request: anonymize PII, preserve audit trail. Skips litigation hold."""
    try:
        result = fulfill_deletion_request(
            request_id,
            actor_id=getattr(_auth, "actor_id", None) or "api",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/consent-revoke")
async def dsar_consent_revoke(
    body: ConsentRevokeInput = Body(...),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Revoke data processing consent for all parties with the given email."""
    count = revoke_consent_by_email(
        body.email,
        actor_id=getattr(_auth, "actor_id", None) or "api",
    )
    return {"email": body.email, "parties_updated": count}


@router.post("/requests/{request_id}/fulfill")
async def dsar_fulfill_access(
    request_id: str,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Fulfill an access request: collect PII and return export."""
    try:
        export = fulfill_access_request(
            request_id,
            actor_id=getattr(_auth, "actor_id", None) or "api",
        )
        return export
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
