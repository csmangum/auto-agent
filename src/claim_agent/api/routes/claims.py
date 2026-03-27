"""Claims API routes: listing, detail, audit log, workflow runs, statistics."""

import asyncio
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import (
    adjuster_identity_scopes_assignee,
    ensure_claim_access_for_adjuster,
    filter_related_claim_ids_for_adjuster,
)
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.api.deps import require_role
from claim_agent.config import get_settings
from claim_agent.exceptions import (
    ClaimAlreadyProcessingError,
    ClaimNotFoundError,
    DomainValidationError,
    InvalidClaimTransitionError,
    ReserveAuthorityError,
)
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import (
    STATUS_ARCHIVED,
    STATUS_PURGED,
    DENIAL_COVERAGE_STATUSES,
    DISPUTABLE_STATUSES,
    SIU_INVESTIGATION_STATUSES,
    THIRD_PARTY_PORTAL_ELIGIBLE_PARTY_TYPES,
    VALID_REPAIR_STATUSES,
)
from sqlalchemy import text

from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.workflow.helpers import WORKFLOW_STAGES
from claim_agent.models.claim import ClaimInput, ClaimRecord
from claim_agent.db.document_repository import build_document_version_groups
from claim_agent.models.claim import ClaimRecord
from claim_agent.models.party import PartyRelationshipType
from claim_agent.models.incident import (
    BIAllocationInput,
    ClaimLinkInput,
    IncidentDetailResponse,
    IncidentInput,
    IncidentOutput,
    IncidentRecord,
    RelatedClaimsResponse,
)
from claim_agent.models.dispute import DisputeType
from claim_agent.models.document import DocumentRequestStatus, DocumentType, ReviewStatus
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.services.bi_allocation import allocate_bi_limits
from claim_agent.services.portal_verification import create_claim_access_token
from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository
from claim_agent.services.repair_shop_portal_tokens import create_repair_shop_access_token
from claim_agent.services.third_party_portal_tokens import create_third_party_access_token
from claim_agent.services.supplemental_request import execute_supplemental_request
from claim_agent.rag.constants import normalize_state
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output
from claim_agent.utils.sanitization import MAX_ACTOR_ID
from claim_agent.utils.sanitization import (
    MAX_ACTOR_ID,
    MAX_DENIAL_REASON,
    MAX_POLICYHOLDER_EVIDENCE,
)
from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from claim_agent.workflow.follow_up_orchestrator import run_follow_up_workflow
from claim_agent.workflow.siu_orchestrator import (
    run_siu_investigation as run_siu_investigation_workflow,
)
from claim_agent.mock_crew.claim_generator import (
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)
import claim_agent.api.routes._claims_helpers as _claims_helpers
from claim_agent.api.routes._claims_helpers import (
    ALLOWED_SORT_FIELDS as _ALLOWED_SORT_FIELDS,
    GenerateClaimRequest,
    GenerateIncidentDetailsRequest,
    PRIORITY_VALUES,
    adjuster_scope_params as _adjuster_scope_params,
    apply_adjuster_claim_filter as _apply_adjuster_claim_filter,
    ALLOWED_DOCUMENT_EXTENSIONS as _ALLOWED_DOCUMENT_EXTENSIONS,
    GenerateClaimRequest,
    GenerateIncidentDetailsRequest,
    VALID_DOCUMENT_TYPES as _VALID_DOCUMENT_TYPES,
    get_claim_context,
    http_already_processing as _http_already_processing,
    process_claim_with_attachments as _process_claim_with_attachments,
    run_workflow_background as _run_workflow_background,
    sanitize_incident_data as _sanitize_incident_data,
    try_run_workflow_background as _try_run_workflow_background,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")





class PartyConsentUpdate(BaseModel):
    """Request body for PATCH /claims/{claim_id}/parties/{party_id}/consent."""

    consent_status: Literal["pending", "granted", "revoked"] = Field(
        ...,
        description="Data processing consent status. Revoked excludes party PII from LLM prompts.",
    )


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


class CreatePartyRelationshipBody(BaseModel):
    """Request body for POST /claims/{claim_id}/party-relationships."""

    from_party_id: int = Field(..., ge=1, description="Subject party (edge tail)")
    to_party_id: int = Field(..., ge=1, description="Related party (edge head)")
    relationship_type: PartyRelationshipType = Field(..., description="Directed relationship type")


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
        token = create_claim_access_token(
            claim_id, party_id=party_id, email=email
        )
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


class AssignRepairShopBody(BaseModel):
    shop_id: str = Field(..., min_length=1, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=500)


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


class ReserveBody(BaseModel):
    """Request body for PATCH /claims/{claim_id}/reserve."""

    reserve_amount: float = Field(..., ge=0, description="New reserve amount in dollars")
    reason: str = Field(default="", max_length=500, description="Reason for change")
    skip_authority_check: bool = Field(
        default=False,
        description="If true, bypass reserve authority limits (admin role only).",
    )


class LitigationHoldBody(BaseModel):
    """Request body for PATCH /claims/{claim_id}/litigation-hold."""

    litigation_hold: bool = Field(..., description="True to set hold, False to clear")


@router.patch("/claims/{claim_id}/litigation-hold", dependencies=[RequireAdjuster])
def patch_claim_litigation_hold(
    claim_id: str,
    body: LitigationHoldBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Set or clear litigation hold. Claims with hold are excluded from retention and DSAR deletion."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.repo.set_litigation_hold(claim_id, body.litigation_hold, actor_id=actor_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return {"claim_id": claim_id, "litigation_hold": body.litigation_hold}


@router.patch("/claims/{claim_id}/reserve", dependencies=[RequireAdjuster])
def patch_claim_reserve(
    claim_id: str,
    body: ReserveBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Set or adjust reserve amount for a claim. Uses adjust_reserve (handles initial set)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    skip = body.skip_authority_check
    if skip and auth.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="skip_authority_check is only allowed for the admin role.",
        )
    try:
        ctx.repo.adjust_reserve(
            claim_id,
            body.reserve_amount,
            reason=body.reason,
            actor_id=actor_id,
            role=auth.role,
            skip_authority_check=skip and auth.role == "admin",
        )
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    except ReserveAuthorityError as e:
        raise HTTPException(
            status_code=403,
            detail=str(e),
        ) from e
    return {"claim_id": claim_id, "reserve_amount": body.reserve_amount}


@router.get("/claims/{claim_id}/reserve-history", dependencies=[RequireAdjuster])
def get_claim_reserve_history(
    claim_id: str,
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get reserve history for a claim, most recent first."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    history = ctx.repo.get_reserve_history(claim_id, limit=limit)
    return {"claim_id": claim_id, "history": history, "limit": limit}


@router.get("/claims/{claim_id}/reserve/adequacy", dependencies=[RequireAdjuster])
def get_claim_reserve_adequacy(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Check reserve adequacy vs estimated_damage and payout_amount.

    Response includes ``warnings`` (human text) and ``warning_codes`` (stable ``RESERVE_*`` strings).
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        result = ctx.repo.check_reserve_adequacy(claim_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return result


@router.get("/claims/{claim_id}/history", dependencies=[RequireAdjuster])
def get_claim_history(
    claim_id: str,
    limit: int | None = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get audit log entries for a claim with optional pagination.

    Omit ``limit`` (or pass no query param) to return the full history,
    preserving backwards-compatible behaviour for existing clients.
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    history, total = ctx.repo.get_claim_history(claim_id, limit=limit, offset=offset)
    return {
        "claim_id": claim_id,
        "history": history,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/claims/{claim_id}/fraud-filings", dependencies=[RequireAdjuster])
def get_claim_fraud_filings(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get fraud report filings for a claim (state bureau, NICB, NISS) for compliance audit."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    filings = ctx.repo.get_fraud_filings_for_claim(claim_id)
    return {"claim_id": claim_id, "filings": filings}


class AddNoteBody(BaseModel):
    note: str = Field(..., min_length=1, description="Note content")
    actor_id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_ACTOR_ID,
        description="Crew name, agent identifier, or 'workflow'",
    )

    @field_validator("note", "actor_id", mode="after")
    @classmethod
    def strip_and_validate_not_blank(cls, v: str, info) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} cannot be blank")
        return stripped


@router.get("/claims/{claim_id}/notes", dependencies=[RequireAdjuster])
def get_claim_notes(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List notes for a claim, ordered by created_at."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    notes = ctx.repo.get_notes(claim_id)
    return {"claim_id": claim_id, "notes": notes}


@router.post("/claims/{claim_id}/notes", dependencies=[RequireAdjuster])
def add_claim_note(
    claim_id: str,
    body: AddNoteBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Add a note to a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        ctx.repo.add_note(claim_id, body.note, body.actor_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return {"claim_id": claim_id, "actor_id": body.actor_id}


@router.get("/claims/{claim_id}/workflows", dependencies=[RequireAdjuster])
def get_claim_workflows(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get workflow runs for a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM workflow_runs WHERE claim_id = :claim_id ORDER BY id ASC"),
            {"claim_id": claim_id},
        ).fetchall()

    return {"claim_id": claim_id, "workflows": [row_to_dict(r) for r in rows]}


@router.get("/claims/{claim_id}/repair-status", dependencies=[RequireAdjuster])
def get_claim_repair_status(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get repair status and history for a partial loss claim."""
    claim_row = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    if claim_row.get("claim_type") != "partial_loss":
        raise HTTPException(
            status_code=400,
            detail="Repair status only applies to partial_loss claims",
        )
    repo = RepairStatusRepository(db_path=get_db_path())
    latest = repo.get_repair_status(claim_id)
    history = repo.get_repair_status_history(claim_id)
    cycle_time_days = repo.get_cycle_time_days(claim_id)
    return {
        "claim_id": claim_id,
        "latest": latest,
        "history": history,
        "cycle_time_days": cycle_time_days,
    }


class RepairStatusUpdateBody(BaseModel):
    """Request body for updating repair status (simulation/dashboard)."""

    status: str = Field(..., min_length=1, max_length=64)
    shop_id: str | None = Field(default=None, max_length=128)
    authorization_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/claims/{claim_id}/repair-status", dependencies=[RequireAdjuster])
def update_claim_repair_status(
    claim_id: str,
    body: RepairStatusUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
):
    """Update repair status (for simulation/dashboard). Infers shop_id from workflow if omitted."""
    if body.status not in VALID_REPAIR_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_REPAIR_STATUSES)}",
        )
    claim_repo = ClaimRepository(db_path=get_db_path())
    claim = ensure_claim_access_for_adjuster(auth, claim_id, claim_repo.get_claim(claim_id))
    if claim.get("claim_type") != "partial_loss":
        raise HTTPException(
            status_code=400,
            detail="Repair status only applies to partial_loss claims",
        )
    shop_id = body.shop_id
    auth_id = body.authorization_id
    if not shop_id or not auth_id:
        runs = claim_repo.get_workflow_runs(claim_id, limit=5)
        for run in runs:
            if run.get("claim_type") != "partial_loss":
                continue
            parsed = _parse_partial_loss_workflow_output(run.get("workflow_output") or "")
            if parsed:
                shop_id = shop_id or str(parsed.get("shop_id", "")).strip()
                auth_id = auth_id or str(parsed.get("authorization_id", "")).strip()
                break
    if not shop_id:
        shop_id = "unknown"
    status_repo = RepairStatusRepository(db_path=get_db_path())
    row_id = status_repo.insert_repair_status(
        claim_id=claim_id,
        shop_id=shop_id,
        status=body.status,
        authorization_id=auth_id,
        notes=body.notes,
    )
    return {"ok": True, "repair_status_id": row_id}


@router.post("/claims/generate")
async def generate_and_submit_claim(
    request: Request,
    body: GenerateClaimRequest = Body(...),
    async_mode: bool = Query(False, alias="async", description="If submit=true, return claim_id immediately and process in background"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Generate claim data via Mock Crew LLM from a prompt, then optionally submit.

    Requires MOCK_CREW_ENABLED=true. The LLM produces realistic ClaimInput JSON
    from the prompt (e.g. "partial loss, Honda Accord, parking lot fender bender").
    If submit=true, the claim is created and the workflow runs. If submit=false,
    returns the generated claim JSON without creating or processing it (useful for
    inspection). When async=true and submit=true, returns claim_id immediately;
    use GET /claims/{claim_id}/status or /stream to poll for completion.
    """
    try:
        claim_input = await asyncio.to_thread(
            generate_claim_from_prompt,
            body.prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    claim_data = claim_input.model_dump(mode="json")
    if not body.submit:
        return {"claim": claim_data, "submitted": False}

    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        if async_mode:
            max_tasks = get_settings().max_concurrent_background_tasks
            async with _claims_helpers.background_tasks_lock:
                if max_tasks > 0 and len(_claims_helpers.background_tasks) >= max_tasks:
                    release_idempotency_on_error(idem_key)
                    raise HTTPException(
                        status_code=503,
                        detail="Too many concurrent background tasks. Retry later.",
                        headers={"Retry-After": "60"},
                    )

        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
            claim_input, None, actor_id, ctx=ctx,
        )

        if async_mode:
            _run_workflow_background(
                claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
            )
            result = {"claim": claim_data, "submitted": True, "claim_id": claim_id}
        else:
            try:
                result = await asyncio.to_thread(
                    run_claim_workflow,
                    claim_data_with_attachments,
                    None,
                    claim_id,
                    actor_id=actor_id,
                    ctx=ctx,
                )
            except ClaimAlreadyProcessingError as e:
                _http_already_processing(e)
            result = {"claim": claim_data, "submitted": True, **result}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post("/claims/generate-incident-details")
async def generate_incident_details(
    body: GenerateIncidentDetailsRequest = Body(...),
    auth: AuthContext = RequireAdjuster,
):
    """Generate incident/damage details via Mock Crew LLM for a given vehicle.

    Requires MOCK_CREW_ENABLED=true. Returns incident_date, incident_description,
    damage_description, and estimated_damage for use in the New Claim form.
    """
    try:
        result = await asyncio.to_thread(
            generate_incident_damage_from_vehicle,
            body.vehicle_year,
            body.vehicle_make,
            body.vehicle_model,
            body.prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except InvalidClaimTransitionError:
        raise
    except Exception as e:
        logger.exception("generate-incident-details failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Incident details generation is temporarily unavailable. Please try again later.",
        ) from e
    return result


@router.post("/incidents", response_model=IncidentOutput)
async def create_incident(
    request: Request,
    incident_input: IncidentInput = Body(..., description="Multi-vehicle incident data"),
    async_mode: bool = Query(False, alias="async", description="Process each claim in background"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create an incident with multiple vehicle claims (multi-vehicle accident).

    One incident can involve multiple vehicles; each vehicle becomes a separate claim
    linked to the incident. Claims are automatically linked as same_incident.
    """
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW

    try:
        # Sanitize incident data before processing
        incident_dict = incident_input.model_dump(mode="python")
        sanitized_incident = _sanitize_incident_data(incident_dict)
        try:
            sanitized_input = IncidentInput.model_validate(sanitized_incident)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=f"Invalid incident data: {e}") from e

        incident_repo = IncidentRepository(db_path=get_db_path())
        incident_id, claim_ids = incident_repo.create_incident(sanitized_input, actor_id=actor_id)

        if async_mode and claim_ids:
            scheduling_status: dict[str, str] = {}
            for claim_id in claim_ids:
                claim = ctx.repo.get_claim(claim_id)
                if claim:
                    claim_data = claim_data_from_row(claim)
                    task = await _try_run_workflow_background(
                        claim_id, claim_data, actor_id, ctx=ctx,
                    )
                    scheduling_status[claim_id] = "scheduled" if task is not None else "capacity_exceeded"
                else:
                    logger.error(
                        "Claim %s created by incident %s not found when scheduling background workflow; "
                        "possible data integrity issue",
                        claim_id,
                        incident_id,
                    )
                    scheduling_status[claim_id] = "claim_not_found"

            result = IncidentOutput(
                incident_id=incident_id,
                claim_ids=claim_ids,
                message=f"Incident {incident_id} created with {len(claim_ids)} claim(s)",
                background_scheduling=scheduling_status,
            )
        else:
            result = IncidentOutput(
                incident_id=incident_id,
                claim_ids=claim_ids,
                message=f"Incident {incident_id} created with {len(claim_ids)} claim(s)",
            )
        store_response_if_idempotent(idem_key, 200, result.model_dump(mode="json"))
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get incident details and linked claims."""
    incident_repo = IncidentRepository(db_path=get_db_path())
    incident = incident_repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    claims = incident_repo.get_claims_by_incident(incident_id)
    if adjuster_identity_scopes_assignee(auth):
        claims = [c for c in claims if (c.get("assignee") or "") == auth.identity]
        if not claims:
            raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentDetailResponse(
        incident=IncidentRecord.model_validate(incident),
        claims=[ClaimRecord.model_validate(c) for c in claims],
    )


@router.post("/claim-links")
async def create_claim_link(
    request: Request,
    link_input: ClaimLinkInput = Body(..., description="Link between two claims"),
    auth: AuthContext = RequireAdjuster,
):
    """Link two claims for cross-carrier or same-incident coordination.

    Use for: opposing_carrier (your insured hit their insured), subrogation,
    cross_carrier, or same_incident when linking claims from different submissions.
    """
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        claim_repo = ClaimRepository(db_path=get_db_path())
        for cid in (link_input.claim_id_a, link_input.claim_id_b):
            ensure_claim_access_for_adjuster(auth, cid, claim_repo.get_claim(cid))
        incident_repo = IncidentRepository(db_path=get_db_path())
        link_id = incident_repo.create_claim_link(
            link_input.claim_id_a,
            link_input.claim_id_b,
            link_input.link_type,
            opposing_carrier=link_input.opposing_carrier,
            notes=link_input.notes,
        )
        if link_id is None:
            raise HTTPException(
                status_code=409,
                detail="A claim link with this combination already exists",
            )
        result = {"link_id": link_id, "message": "Claim link created"}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.get("/claims/{claim_id}/related", response_model=RelatedClaimsResponse)
async def get_related_claims(
    claim_id: str,
    link_type: Optional[str] = Query(None, description="Filter by link type"),
    auth: AuthContext = RequireAdjuster,
):
    """Get claims related to this claim (same incident, opposing carrier, etc.)."""
    claim_repo = ClaimRepository(db_path=get_db_path())
    ensure_claim_access_for_adjuster(auth, claim_id, claim_repo.get_claim(claim_id))
    incident_repo = IncidentRepository(db_path=get_db_path())
    related = incident_repo.get_related_claims(claim_id, link_type=link_type)
    if adjuster_identity_scopes_assignee(auth):
        related = filter_related_claim_ids_for_adjuster(auth, claim_repo, related)
    return RelatedClaimsResponse(claim_id=claim_id, related_claim_ids=related)


@router.post("/bi-allocation")
async def allocate_bi(
    allocation_input: BIAllocationInput = Body(..., description="BI limit allocation request"),
    auth: AuthContext = RequireAdjuster,
):
    """Allocate BI per-accident limit across multiple claimants when demands exceed limit.

    Use when multiple BI claimants exceed the policy's per_accident limit.
    Methods: proportional (default), severity_weighted, equal.
    """
    claim_repo = ClaimRepository(db_path=get_db_path())
    ensure_claim_access_for_adjuster(
        auth, allocation_input.claim_id, claim_repo.get_claim(allocation_input.claim_id)
    )
    result = allocate_bi_limits(allocation_input)
    return result.model_dump()





@router.post("/claims/{claim_id}/review")
async def run_claim_review(
    claim_id: str,
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Run supervisor/compliance review on the claim process. Requires supervisor role.

    Returns a ClaimReviewReport with issues, compliance_checks, and recommendations.
    The report is persisted to the audit log.
    """
    from claim_agent.workflow.claim_review_orchestrator import run_claim_review as _run_claim_review

    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    actor_id = auth.identity if auth.identity != "anonymous" else "claim_review_crew"
    report = await asyncio.to_thread(
        _run_claim_review,
        claim_id,
        actor_id=actor_id,
        ctx=ctx,
    )

    report_json = report.model_dump_json()
    ctx.repo.record_claim_review(claim_id, report_json, actor_id)

    return report.model_dump(mode="json")
@router.post("/claims/{claim_id}/reprocess")
async def reprocess_claim(
    claim_id: str,
    from_stage: Optional[str] = Query(
        None,
        description=(
            "Resume from this stage using checkpoints from the most recent workflow run. "
            f"Must be one of: {', '.join(WORKFLOW_STAGES)}"
        ),
    ),
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Re-run workflow for an existing claim. Requires supervisor role.

    Pass ``from_stage`` to resume from a specific stage using checkpoints from
    the most recent workflow run.
    """
    if from_stage is not None and from_stage not in WORKFLOW_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"from_stage must be one of {', '.join(WORKFLOW_STAGES)}",
        )

    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data for reprocess: {e}") from e

    resume_run_id: str | None = None
    if from_stage is not None:
        resume_run_id = ctx.repo.get_latest_checkpointed_run_id(claim_id)
        if resume_run_id is None:
            from_stage = None

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        result = await asyncio.to_thread(
            run_claim_workflow,
            claim_data,
            existing_claim_id=claim_id,
            actor_id=actor_id,
            resume_run_id=resume_run_id,
            from_stage=from_stage,
            ctx=ctx,
        )
    except ClaimAlreadyProcessingError as e:
        _http_already_processing(e)
    return result
class DisputeBody(BaseModel):
    dispute_type: str = Field(..., description="Dispute type: liability_determination, valuation_disagreement, repair_estimate, or deductible_application")
    dispute_description: str = Field(..., description="Policyholder's description of the dispute")
    policyholder_evidence: Optional[str] = Field(default=None, description="Optional supporting evidence references")


class DisputeResponse(BaseModel):
    """Response from filing a policyholder dispute."""

    claim_id: str = Field(..., description="Claim ID")
    dispute_type: str = Field(..., description="Dispute category")
    resolution_type: str = Field(..., description="auto_resolved or escalated")
    status: str = Field(..., description="Final claim status after dispute workflow")
    workflow_output: str = Field(..., description="Raw workflow output from dispute crew")
    adjusted_amount: Optional[float] = Field(default=None, description="Revised payout if auto-resolved and adjusted")
    summary: str = Field(..., description="Short summary of the resolution")


class SupplementalBody(BaseModel):
    """Request body for filing a supplemental damage report."""

    supplemental_damage_description: str = Field(
        ...,
        max_length=2000,
        description="Description of the additional damage discovered during repair",
    )
    reported_by: Optional[Literal["shop", "adjuster", "policyholder"]] = Field(
        default=None,
        description="Who reported: shop, adjuster, or policyholder",
    )


class SupplementalResponse(BaseModel):
    """Response from supplemental workflow."""

    claim_id: str = Field(..., description="Claim ID")
    status: str = Field(..., description="Claim status after supplemental workflow")
    supplemental_amount: Optional[float] = Field(
        default=None,
        description="Supplemental estimate amount",
    )
    combined_insurance_pays: Optional[float] = Field(
        default=None,
        description="Combined original + supplemental insurance payment",
    )
    workflow_output: str = Field(..., description="Raw workflow output")
    summary: str = Field(..., description="Short summary")


@router.post("/claims/{claim_id}/dispute", response_model=DisputeResponse)
async def file_dispute(
    claim_id: str,
    body: DisputeBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """File a policyholder dispute on an existing claim.

    Runs the dispute resolution workflow which auto-resolves simple disputes
    (valuation, repair estimate, deductible) and escalates complex ones
    (liability) to human adjusters.
    """
    claim = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    claim_status = claim.get("status")
    if claim_status not in DISPUTABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim cannot be disputed in status {claim_status!r}. "
                f"Disputes are allowed only for claims with status: {', '.join(DISPUTABLE_STATUSES)}."
            ),
        )

    try:
        DisputeType(body.dispute_type)
    except ValueError:
        valid = [t.value for t in DisputeType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dispute_type. Must be one of: {', '.join(valid)}",
        )

    dispute_data = {
        "claim_id": claim_id,
        "dispute_type": body.dispute_type,
        "dispute_description": body.dispute_description,
        "policyholder_evidence": body.policyholder_evidence,
    }

    result = await asyncio.to_thread(
        run_dispute_workflow,
        dispute_data,
        ctx=ctx,
    )
    return result


class DenialCoverageBody(BaseModel):
    """Request body for denial/coverage dispute workflow."""

    denial_reason: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DENIAL_REASON,
        description="Stated reason for the denial",
    )
    policyholder_evidence: Optional[str] = Field(
        default=None,
        max_length=MAX_POLICYHOLDER_EVIDENCE,
        description="Optional evidence or argument from policyholder",
    )
    state: Optional[str] = Field(
        default="California",
        description="State jurisdiction for compliance (California, Texas, Florida, New York)",
    )


class DenialCoverageResponse(BaseModel):
    """Response from denial/coverage workflow."""

    claim_id: str = Field(..., description="Claim ID")
    outcome: str = Field(
        ...,
        description="outcome: uphold_denial, route_to_appeal, or escalated",
    )
    status: str = Field(..., description="Claim status after workflow")
    workflow_output: str = Field(..., description="Raw workflow output")
    summary: str = Field(..., description="Short summary")


@router.post("/claims/{claim_id}/denial-coverage", response_model=DenialCoverageResponse)
async def run_denial_coverage(
    claim_id: str,
    body: DenialCoverageBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Run denial/coverage dispute workflow on a denied claim.

    Reviews denial reason, verifies coverage/exclusions, and either generates
    a denial letter (uphold) or routes to appeal.
    """
    claim = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    claim_status = claim.get("status")
    if claim_status not in DENIAL_COVERAGE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim cannot run denial/coverage workflow in status {claim_status!r}. "
                f"Allowed statuses: {', '.join(DENIAL_COVERAGE_STATUSES)}."
            ),
        )

    denial_data = {
        "claim_id": claim_id,
        "denial_reason": body.denial_reason,
        "policyholder_evidence": body.policyholder_evidence,
    }
    try:
        state = normalize_state(body.state or "California")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = await asyncio.to_thread(
        run_denial_coverage_workflow,
        denial_data,
        ctx=ctx,
        state=state,
    )
    return result


@router.post("/claims/{claim_id}/supplemental", response_model=SupplementalResponse)
async def file_supplemental(
    claim_id: str,
    body: SupplementalBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """File a supplemental damage report on an existing partial loss claim.

    Runs the supplemental workflow when additional damage is discovered during
    repair. Validates the report, compares to original estimate, calculates
    supplemental amount, and updates the repair authorization.
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    try:
        return await execute_supplemental_request(
            claim_id=claim_id,
            supplemental_damage_description=body.supplemental_damage_description,
            reported_by=body.reported_by,
            ctx=ctx,
        )
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        msg = str(e)
        code = 409 if "cannot receive supplemental" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from e
