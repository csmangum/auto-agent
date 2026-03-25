"""Claimant self-service portal API routes.

All endpoints require claimant verification via headers:
- X-Claim-Access-Token (token mode)
- X-Claim-Id + X-Policy-Number + X-Vin (policy_vin mode)
- X-Claim-Id + X-Email (email mode, when DSAR_VERIFICATION_REQUIRED=false)
"""

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from claim_agent.api.portal_deps import (
    PortalSession,
    require_claimant_access,
    require_portal_session,
)
from claim_agent.api.routes.claims import (
    _ALLOWED_DOCUMENT_EXTENSIONS,
    _VALID_DOCUMENT_TYPES,
    _get_doc_repo,
    _max_upload_file_size_bytes,
    _maybe_update_document_request_on_receipt,
    _upload_file_size_exceeded_detail,
)
from claim_agent.context import ClaimContext
from claim_agent.db.constants import DISPUTABLE_STATUSES
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.db.payment_repository import PaymentRepository
from claim_agent.db.rental_repository import RentalAuthorizationRepository
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.dispute import DisputeType
from claim_agent.models.document import DocumentType
from claim_agent.services.portal_verification import ClaimantContext
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from fastapi.responses import FileResponse

router = APIRouter(prefix="/portal", tags=["portal"])

# Fields from the claims table that are safe to expose to claimants (and repair portal).
# Internal/admin fields (reserve_amount, review_notes, siu_case_id,
# litigation_hold, assignee, priority, due_at, review_started_at, etc.)
# are intentionally excluded.
PORTAL_CLAIM_FIELDS = [
    "id",
    "policy_number",
    "vin",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "incident_date",
    "incident_description",
    "damage_description",
    "estimated_damage",
    "claim_type",
    "status",
    "payout_amount",
    "loss_state",
    "liability_percentage",
    "incident_id",
    "created_at",
    "updated_at",
    "attachments",
]


def _resolve_portal_attachment_urls(
    claim: dict[str, Any],
    *,
    attachments_api_base: str = "/api/portal",
) -> dict[str, Any]:
    """Rewrite attachment paths to portal-accessible download URLs.

    Unlike the adjuster resolver, this generates URLs under
    ``{attachments_api_base}/claims/{id}/attachments/...``.
    """
    import json

    claim_id = claim.get("id", "")
    raw = claim.get("attachments")
    if not raw:
        return claim

    try:
        attachments = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return claim

    if not isinstance(attachments, list):
        return claim

    updated = []
    for att in attachments:
        if isinstance(att, dict):
            key = att.get("storage_key") or att.get("key") or ""
            if key:
                att = {
                    **att,
                    "url": f"{attachments_api_base}/claims/{claim_id}/attachments/{key}",
                }
        updated.append(att)

    return {**claim, "attachments": updated}


class RecordFollowUpResponseBody(BaseModel):
    """Request body for POST /portal/claims/{claim_id}/follow-up/record-response."""

    message_id: int = Field(..., description="Follow-up message ID")
    response_content: str = Field(
        ..., min_length=1, max_length=5000, description="User's response text"
    )


class DisputeBody(BaseModel):
    """Request body for POST /portal/claims/{claim_id}/dispute."""

    dispute_type: str = Field(
        ...,
        description="Dispute type: liability_determination, valuation_disagreement, repair_estimate, or deductible_application",
    )
    dispute_description: str = Field(
        ..., description="Policyholder's description of the dispute"
    )
    policyholder_evidence: Optional[str] = Field(
        default=None, description="Optional supporting evidence references"
    )


def _get_claim_repo() -> ClaimRepository:
    return ClaimRepository(db_path=get_db_path())


def _get_payment_repo() -> PaymentRepository:
    return PaymentRepository(db_path=get_db_path())


def _get_rental_repo() -> RentalAuthorizationRepository:
    return RentalAuthorizationRepository(db_path=get_db_path())


@router.get("/claims")
def list_portal_claims(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: PortalSession = Depends(require_portal_session),
):
    """List claims the claimant can access."""
    if not session.claim_ids:
        return {"claims": [], "total": 0, "limit": limit, "offset": offset}

    placeholders = ",".join([f":cid{i}" for i in range(len(session.claim_ids))])
    id_params: dict[str, str] = {f"cid{i}": cid for i, cid in enumerate(session.claim_ids)}
    safe_fields = ", ".join(PORTAL_CLAIM_FIELDS)
    list_params: dict[str, Any] = {**id_params, "limit": limit, "offset": offset}

    with get_connection() as conn:
        count_row = conn.execute(
            text(f"SELECT COUNT(*) as cnt FROM claims WHERE id IN ({placeholders})"),
            id_params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            text(f"""
                SELECT {safe_fields} FROM claims WHERE id IN ({placeholders})
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset
            """),
            list_params,
        ).fetchall()

    claims = []
    for r in rows:
        d = row_to_dict(r)
        claims.append(_resolve_portal_attachment_urls(d))

    return {"claims": claims, "total": total, "limit": limit, "offset": offset}


@router.get("/claims/{claim_id}")
def get_portal_claim(
    claim_id: str,
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Get claim detail (status, timeline, messages, parties)."""
    repo = _get_claim_repo()
    row = repo.get_claim(claim_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    result = _resolve_portal_attachment_urls(row)
    result["notes"] = []  # Claimant does not see internal notes
    result["follow_up_messages"] = repo.get_follow_up_messages(claim_id)
    result["parties"] = repo.get_claim_parties(claim_id)
    result["tasks"] = []
    result["tasks_total"] = 0
    result["subrogation_cases"] = []
    return result


@router.get("/claims/{claim_id}/history")
def get_portal_claim_history(
    claim_id: str,
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Get claim audit history (timeline)."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    history = repo.get_claim_history(claim_id)
    return {"claim_id": claim_id, "history": history}


@router.get("/claims/{claim_id}/documents")
def list_portal_documents(
    claim_id: str,
    document_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """List documents for a claim."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    doc_repo = _get_doc_repo()
    documents, total = doc_repo.list_documents(
        claim_id, document_type=document_type, review_status=None, limit=limit, offset=offset
    )
    storage = get_storage_adapter()
    portal_actor = claimant.identity or "portal-claimant"
    for doc in documents:
        sk = doc.get("storage_key", "")
        if sk:
            doc["url"] = storage.get_url(claim_id, sk)
            if isinstance(storage, S3StorageAdapter):
                repo.insert_document_accessed_audit(
                    claim_id,
                    storage_key=sk,
                    actor_id=portal_actor,
                    channel="portal",
                )
        else:
            doc["url"] = None
    return {"claim_id": claim_id, "documents": documents, "total": total, "limit": limit, "offset": offset}


@router.get("/claims/{claim_id}/document-requests")
def list_portal_document_requests(
    claim_id: str,
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """List document requests (pending items from adjuster)."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    doc_repo = _get_doc_repo()
    requests, total = doc_repo.list_document_requests(
        claim_id, status=status, limit=limit, offset=offset
    )
    return {"claim_id": claim_id, "document_requests": requests, "total": total, "limit": limit, "offset": offset}


@router.get("/claims/{claim_id}/repair-status")
def get_portal_repair_status(
    claim_id: str,
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Get repair status and history for partial loss claims."""
    repo = _get_claim_repo()
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    if claim.get("claim_type") != "partial_loss":
        return {"claim_id": claim_id, "latest": None, "history": [], "cycle_time_days": None}

    status_repo = RepairStatusRepository(db_path=get_db_path())
    latest = status_repo.get_repair_status(claim_id)
    history = status_repo.get_repair_status_history(claim_id)
    cycle_time_days = status_repo.get_cycle_time_days(claim_id)
    return {
        "claim_id": claim_id,
        "latest": latest,
        "history": history,
        "cycle_time_days": cycle_time_days,
    }


@router.get("/claims/{claim_id}/payments")
def list_portal_payments(
    claim_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """List payments for a claim (read-only)."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    payment_repo = _get_payment_repo()
    payments, total = payment_repo.get_payments_for_claim(
        claim_id, status=None, limit=limit, offset=offset
    )
    return {"claim_id": claim_id, "payments": payments, "total": total, "limit": limit, "offset": offset}


@router.get("/claims/{claim_id}/rental-summary")
def get_portal_rental_summary(
    claim_id: str,
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Get the sanitized rental authorization summary for a claim.

    Returns the structured rental entitlement (authorized days, daily cap,
    direct-bill flag, status, and approved amount) without exposing internal
    reservation or agency references.

    Returns ``{"claim_id": ..., "rental": null}`` when no rental authorization
    has been persisted yet for this claim.
    """
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    rental_repo = _get_rental_repo()
    summary = rental_repo.get_portal_summary(claim_id)
    return {"claim_id": claim_id, "rental": summary}


@router.post("/claims/{claim_id}/documents")
async def upload_portal_document(
    claim_id: str,
    file: UploadFile = File(...),
    document_type: Optional[str] = Query(None),
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Upload a document for a claim."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")
    ext = (file.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in _ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(sorted(_ALLOWED_DOCUMENT_EXTENSIONS))}",
        )
    chunks: list[bytes] = []
    total_size = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > _max_upload_file_size_bytes():
            raise HTTPException(status_code=413, detail=_upload_file_size_exceeded_detail())
        chunks.append(chunk)
    content = b"".join(chunks)
    if document_type is not None and document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {sorted(_VALID_DOCUMENT_TYPES)}",
        )
    storage = get_storage_adapter()
    stored_key = storage.save(claim_id=claim_id, filename=file.filename, content=content)
    doc_type = document_type or attachment_type_to_document_type(
        infer_attachment_type(file.filename)
    ).value
    if doc_type not in _VALID_DOCUMENT_TYPES:
        doc_type = DocumentType.OTHER.value
    doc_repo = _get_doc_repo()
    doc_id = doc_repo.add_document(
        claim_id,
        stored_key,
        document_type=doc_type,
        received_from="claimant",
    )
    _maybe_update_document_request_on_receipt(doc_repo, repo, claim_id, doc_type)
    doc = doc_repo.get_document(doc_id)
    if doc:
        doc["url"] = storage.get_url(claim_id, stored_key)
        if isinstance(storage, S3StorageAdapter):
            portal_actor = claimant.identity or "portal-claimant"
            repo.insert_document_accessed_audit(
                claim_id,
                storage_key=stored_key,
                actor_id=portal_actor,
                channel="portal",
            )
    return {"claim_id": claim_id, "document_id": doc_id, "document": doc}


@router.get("/claims/{claim_id}/attachments/{key}")
def get_portal_attachment(
    claim_id: str,
    key: str,
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Download an attachment file. Local storage only."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    storage = get_storage_adapter()
    if not isinstance(storage, LocalStorageAdapter):
        raise HTTPException(
            status_code=404,
            detail="Attachment download is only available for local storage",
        )

    try:
        file_path = storage.get_path(claim_id, key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attachment key") from None
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Attachment not found: {key}")

    actor_id = claimant.identity or "portal-claimant"
    repo.insert_document_download_audit(
        claim_id,
        storage_key=key,
        actor_id=actor_id,
        channel="portal",
    )
    return FileResponse(path=str(file_path), filename=key)


@router.post("/claims/{claim_id}/follow-up/record-response")
def record_portal_follow_up_response(
    claim_id: str,
    body: RecordFollowUpResponseBody = Body(...),
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """Record claimant's response to a follow-up message."""
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    try:
        repo.record_follow_up_response(
            body.message_id,
            body.response_content,
            actor_id=claimant.identity or "portal-claimant",
            expected_claim_id=claim_id,
        )
        return {"success": True, "message": "Response recorded"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/claims/{claim_id}/dispute")
async def file_portal_dispute(
    claim_id: str,
    body: DisputeBody = Body(...),
    claimant: ClaimantContext = Depends(require_claimant_access),
):
    """File a policyholder dispute on an existing claim."""
    ctx = ClaimContext.from_defaults(db_path=get_db_path())
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

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
