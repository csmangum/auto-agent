"""DSAR (Data Subject Access Request) API routes for privacy compliance."""

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.compliance.dsar_state_rules import (
    get_dsar_form_schema,
    get_dsar_state_rules,
    get_supported_dsar_states,
)
from claim_agent.config import get_settings
from claim_agent.services.dsar import (
    assert_self_service_party_binding,
    fulfill_access_request,
    fulfill_deletion_request,
    get_dsar_request,
    list_dsar_requests,
    revoke_consent_by_email,
    submit_access_request,
    submit_deletion_request,
)
from claim_agent.services.dsar_verification import (
    RateLimitExceeded,
    claimant_identifiers_match,
    get_verification_token,
    is_verified,
    request_otp,
    verify_otp,
)

router = APIRouter(prefix="/dsar", tags=["dsar"])


def _enforce_self_service_otp_and_party_binding(
    verification_id: str,
    claimant_identifier: str,
    verification_data: dict[str, Any],
) -> None:
    """Raise ``HTTPException`` if OTP session or party binding is invalid."""
    if not is_verified(verification_id):
        raise HTTPException(
            status_code=403,
            detail="verification_id is not verified or has expired. Complete OTP verification first.",
        )
    token = get_verification_token(verification_id)
    if token is None:
        raise HTTPException(
            status_code=403,
            detail="verification_id is not verified or has expired. Complete OTP verification first.",
        )
    if not claimant_identifiers_match(
        token["claimant_identifier"], claimant_identifier, token["channel"]
    ):
        raise HTTPException(
            status_code=403,
            detail="claimant_identifier does not match the OTP verification session.",
        )
    try:
        assert_self_service_party_binding(
            claimant_identifier, token["channel"], verification_data
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


class AccessRequestInput(BaseModel):
    """Request body for POST /dsar/access."""

    claimant_identifier: str = Field(..., description="Email or identifier for the claimant")
    claim_id: Optional[str] = Field(None, description="Claim ID for verification")
    policy_number: Optional[str] = Field(None, description="Policy number for verification")
    vin: Optional[str] = Field(None, description="VIN for verification")
    state: Optional[str] = Field(
        None,
        description=(
            "Consumer's state of residence (e.g., 'California'). When provided, "
            "state-specific response metadata and timelines are included in the export."
        ),
    )


@router.post("/access")
def dsar_submit_access(
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
    
    has_claim_id = bool(body.claim_id)
    has_both_policy_and_vin = bool(body.policy_number) and bool(body.vin)
    
    if not (has_claim_id or has_both_policy_and_vin):
        raise HTTPException(
            status_code=400,
            detail="Provide either claim_id or (policy_number and vin) for verification",
        )
    
    request_id = submit_access_request(
        claimant_identifier=body.claimant_identifier,
        verification_data=verification_data,
        actor_id=_auth.identity or "api",
        state=body.state,
    )
    return {"request_id": request_id, "status": "pending"}


@router.get("/requests/{request_id}")
def dsar_get_request(
    request_id: str,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Get DSAR request status by request_id."""
    req = get_dsar_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="DSAR request not found")
    return req


@router.get("/requests")
def dsar_list_requests(
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
    state: Optional[str] = Field(
        None,
        description="Consumer's state of residence (e.g., 'California'). Stored for audit.",
    )


@router.post("/deletion")
def dsar_submit_deletion(
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
    
    has_claim_id = bool(body.claim_id)
    has_both_policy_and_vin = bool(body.policy_number) and bool(body.vin)
    
    if not (has_claim_id or has_both_policy_and_vin):
        raise HTTPException(
            status_code=400,
            detail="Provide either claim_id or (policy_number and vin) for verification",
        )
    
    request_id = submit_deletion_request(
        claimant_identifier=body.claimant_identifier,
        verification_data=verification_data,
        actor_id=_auth.identity or "api",
        state=body.state,
    )
    return {"request_id": request_id, "status": "pending"}


@router.post("/deletion/fulfill/{request_id}")
def dsar_fulfill_deletion(
    request_id: str,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Fulfill a deletion request: anonymize PII, preserve audit trail. Skips litigation hold."""
    req = get_dsar_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="DSAR request not found")
    try:
        result = fulfill_deletion_request(
            request_id,
            actor_id=_auth.identity or "api",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/consent-revoke")
def dsar_consent_revoke(
    body: ConsentRevokeInput = Body(...),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Revoke data processing consent for all parties with the given email."""
    count = revoke_consent_by_email(
        body.email,
        actor_id=_auth.identity or "api",
    )
    return {"email": body.email, "parties_updated": count}


@router.post("/requests/{request_id}/fulfill")
def dsar_fulfill_access(
    request_id: str,
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Fulfill an access request: collect PII and return export."""
    req = get_dsar_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="DSAR request not found")
    try:
        export = fulfill_access_request(
            request_id,
            actor_id=_auth.identity or "api",
        )
        return export
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Self-service OTP verification endpoints (no admin role required)
# ---------------------------------------------------------------------------


class OTPRequestInput(BaseModel):
    """Request body for POST /dsar/verify/request."""

    claimant_identifier: str = Field(
        ..., description="Email address (channel='email') or phone number (channel='sms')"
    )
    channel: str = Field(..., description="Delivery channel: 'email' or 'sms'")


class OTPConfirmInput(BaseModel):
    """Request body for POST /dsar/verify/confirm."""

    verification_id: str = Field(..., description="verification_id returned by /dsar/verify/request")
    code: str = Field(..., description="Numeric OTP code delivered to the claimant")


class SelfServiceAccessInput(BaseModel):
    """Request body for POST /dsar/self-service/access."""

    claimant_identifier: str = Field(..., description="Email or identifier for the claimant")
    verification_id: str = Field(..., description="Verified OTP verification_id")
    claim_id: Optional[str] = Field(None, description="Claim ID for data lookup")
    policy_number: Optional[str] = Field(None, description="Policy number for data lookup")
    vin: Optional[str] = Field(None, description="VIN for data lookup")


class SelfServiceDeletionInput(BaseModel):
    """Request body for POST /dsar/self-service/deletion."""

    claimant_identifier: str = Field(..., description="Email or identifier for the claimant")
    verification_id: str = Field(..., description="Verified OTP verification_id")
    claim_id: Optional[str] = Field(None, description="Claim ID for data lookup")
    policy_number: Optional[str] = Field(None, description="Policy number for data lookup")
    vin: Optional[str] = Field(None, description="VIN for data lookup")


@router.post("/verify/request")
def dsar_otp_request(body: OTPRequestInput = Body(...)) -> dict[str, Any]:
    """Request a DSAR OTP (one-time password) for self-service identity verification.

    Delivers a numeric OTP to the claimant via email or SMS.  Returns a
    ``verification_id`` to use in ``POST /dsar/verify/confirm``.

    Rate-limited per claimant identifier to prevent abuse.
    """
    settings = get_settings()
    if not settings.privacy.otp_enabled:
        raise HTTPException(
            status_code=403,
            detail="OTP verification is disabled. Contact the administrator for assistance.",
        )

    try:
        verification_id = request_otp(body.claimant_identifier, body.channel)
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ttl = settings.privacy.otp_ttl_minutes
    return {
        "verification_id": verification_id,
        "channel": body.channel,
        "expires_in_minutes": ttl,
        "message": f"OTP sent via {body.channel}. Use verification_id to confirm.",
    }


@router.post("/verify/confirm")
def dsar_otp_confirm(body: OTPConfirmInput = Body(...)) -> dict[str, Any]:
    """Confirm a DSAR OTP code.

    Validates the code submitted by the claimant.  On success the
    ``verification_id`` can be used in ``POST /dsar/self-service/access`` or
    ``POST /dsar/self-service/deletion``.

    Records all verification attempts in the audit log.
    """
    if not get_settings().privacy.otp_enabled:
        raise HTTPException(
            status_code=403,
            detail="OTP verification is disabled. Contact the administrator for assistance.",
        )

    try:
        result = verify_otp(body.verification_id, body.code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    status_code = 200 if result["verified"] else 400
    if status_code == 400:
        raise HTTPException(status_code=400, detail=result["message"])

    token = get_verification_token(body.verification_id)
    return {
        "verified": True,
        "verification_id": body.verification_id,
        "claimant_identifier": token["claimant_identifier"] if token else None,
        "message": result["message"],
    }


@router.post("/self-service/access")
def dsar_self_service_access(body: SelfServiceAccessInput = Body(...)) -> dict[str, Any]:
    """Submit a self-service DSAR access request authenticated by OTP.

    Requires a ``verification_id`` that has been successfully confirmed via
    ``POST /dsar/verify/confirm``.  The token must still be within its TTL.

    Provide either ``claim_id`` or both ``policy_number`` and ``vin`` for
    claim-data lookup.
    """
    if not get_settings().privacy.otp_enabled:
        raise HTTPException(
            status_code=403,
            detail="OTP verification is disabled. Contact the administrator for assistance.",
        )

    has_claim_id = bool(body.claim_id)
    has_policy_and_vin = bool(body.policy_number) and bool(body.vin)
    if not (has_claim_id or has_policy_and_vin):
        raise HTTPException(
            status_code=400,
            detail="Provide either claim_id or (policy_number and vin) for verification",
        )

    verification_data: dict[str, Any] = {}
    if body.claim_id:
        verification_data["claim_id"] = body.claim_id
    if body.policy_number:
        verification_data["policy_number"] = body.policy_number
    if body.vin:
        verification_data["vin"] = body.vin

    _enforce_self_service_otp_and_party_binding(
        body.verification_id, body.claimant_identifier, verification_data
    )

    request_id = submit_access_request(
        claimant_identifier=body.claimant_identifier,
        verification_data=verification_data,
        actor_id=f"otp:{body.verification_id}",
    )
    return {"request_id": request_id, "status": "pending"}


@router.post("/self-service/deletion")
def dsar_self_service_deletion(body: SelfServiceDeletionInput = Body(...)) -> dict[str, Any]:
    """Submit a self-service DSAR deletion request authenticated by OTP.

    Requires a ``verification_id`` that has been successfully confirmed via
    ``POST /dsar/verify/confirm``.  The token must still be within its TTL.

    Provide either ``claim_id`` or both ``policy_number`` and ``vin`` for
    claim-data lookup.
    """
    if not get_settings().privacy.otp_enabled:
        raise HTTPException(
            status_code=403,
            detail="OTP verification is disabled. Contact the administrator for assistance.",
        )

    has_claim_id = bool(body.claim_id)
    has_policy_and_vin = bool(body.policy_number) and bool(body.vin)
    if not (has_claim_id or has_policy_and_vin):
        raise HTTPException(
            status_code=400,
            detail="Provide either claim_id or (policy_number and vin) for verification",
        )

    verification_data: dict[str, Any] = {}
    if body.claim_id:
        verification_data["claim_id"] = body.claim_id
    if body.policy_number:
        verification_data["policy_number"] = body.policy_number
    if body.vin:
        verification_data["vin"] = body.vin

    _enforce_self_service_otp_and_party_binding(
        body.verification_id, body.claimant_identifier, verification_data
    )

    request_id = submit_deletion_request(
        claimant_identifier=body.claimant_identifier,
        verification_data=verification_data,
        actor_id=f"otp:{body.verification_id}",
    )
    return {"request_id": request_id, "status": "pending"}


@router.get("/form-schema")
def dsar_form_schema(
    state: Optional[str] = Query(None, description="Consumer's state of residence (e.g., 'California')"),
    request_type: str = Query("access", description="Request type: 'access' or 'deletion'"),
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """Return the DSAR form schema for the given state and request type.

    Describes the required fields, consumer rights, data categories, response
    timelines, and applicable privacy law for the state. Use this to render a
    guided intake form or validate submission data on the client.

    When ``state`` is omitted or unsupported, a generic fallback schema is returned.
    """
    if request_type not in ("access", "deletion"):
        raise HTTPException(status_code=400, detail="request_type must be 'access' or 'deletion'")
    return get_dsar_form_schema(state, request_type=request_type)


@router.get("/state-requirements")
def dsar_state_requirements(
    _auth: AuthContext = require_role("admin"),
) -> dict[str, Any]:
    """List all states with defined DSAR requirements.

    Returns a summary of each supported state's applicable privacy law, response
    deadline, extension allowance, and consumer rights.
    """
    supported = get_supported_dsar_states()
    summaries = []
    for state_name in supported:
        rules = get_dsar_state_rules(state_name)
        if rules:
            summaries.append(
                {
                    "state": rules.state,
                    "law_name": rules.law_name,
                    "response_days": rules.response_days,
                    "extension_days": rules.extension_days,
                    "consumer_rights": rules.consumer_rights,
                    "annual_request_limit": rules.annual_request_limit,
                }
            )
    return {"supported_states": summaries, "total": len(summaries)}
