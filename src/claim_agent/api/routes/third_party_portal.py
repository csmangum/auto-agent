"""Third-party self-service portal API (per-claim magic token).

Exposes a minimal PII view for counterparties (witness, attorney, provider, lienholder)
and related actions. Uses X-Third-Party-Access-Token (not claimant portal headers).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from claim_agent.api.routes.claims import (
    _ALLOWED_DOCUMENT_EXTENSIONS,
    _VALID_DOCUMENT_TYPES,
    _get_doc_repo,
    _max_upload_file_size_bytes,
    _maybe_update_document_request_on_receipt,
)
from claim_agent.api.routes.portal import (
    DisputeBody,
    RecordFollowUpResponseBody,
    _resolve_portal_attachment_urls,
)
from claim_agent.api.third_party_portal_deps import (
    ThirdPartyPortalContext,
    require_third_party_portal_access,
)
from claim_agent.context import ClaimContext
from claim_agent.db.constants import DISPUTABLE_STATUSES
from claim_agent.db.database import get_db_path
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.dispute import DisputeType
from claim_agent.models.document import DocumentType
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow

router = APIRouter(prefix="/third-party-portal", tags=["third-party-portal"])

_ATTACH_BASE = "/api/third-party-portal"

# Subset of claimant portal fields: no policy_number or vin (minimal PII).
# Includes payout_amount and liability_percentage for subrogation / demand context; deployers
# with stricter data minimization may fork or gate these fields. Policyholder direct contact
# is not exposed here (use follow-up messages / adjuster channels).
THIRD_PARTY_PORTAL_CLAIM_FIELDS = [
    "id",
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


def _tp_ctx_dep(claim_id: str, request: Request) -> ThirdPartyPortalContext:
    return require_third_party_portal_access(request, claim_id)


def _get_claim_repo() -> ClaimRepository:
    return ClaimRepository(db_path=get_db_path())


def _shape_third_party_claim(row: dict[str, Any]) -> dict[str, Any]:
    base = {k: row.get(k) for k in THIRD_PARTY_PORTAL_CLAIM_FIELDS}
    return _resolve_portal_attachment_urls(base, attachments_api_base=_ATTACH_BASE)


def _shape_third_party_audit_entry(row: dict[str, Any]) -> dict[str, Any]:
    """Third parties: status timeline only (no internal audit blobs)."""
    return {
        "id": row.get("id"),
        "action": row.get("action"),
        "old_status": row.get("old_status"),
        "new_status": row.get("new_status"),
        "created_at": row.get("created_at"),
    }


@router.get("/claims/{claim_id}")
def get_third_party_portal_claim(
    claim_id: str,
    _tp_ctx: ThirdPartyPortalContext = Depends(_tp_ctx_dep),
):
    repo = _get_claim_repo()
    row = repo.get_claim(claim_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    result = _shape_third_party_claim(row)
    result["notes"] = []
    all_follow_ups = repo.get_follow_up_messages(claim_id)
    result["follow_up_messages"] = [
        msg for msg in all_follow_ups if (msg.get("user_type") or "") == "other"
    ]
    result["parties"] = []
    result["tasks"] = []
    result["tasks_total"] = 0
    result["subrogation_cases"] = []
    return result


@router.get("/claims/{claim_id}/history")
def get_third_party_portal_claim_history(
    claim_id: str,
    _ctx: ThirdPartyPortalContext = Depends(_tp_ctx_dep),
):
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    history_rows, history_total = repo.get_claim_history(claim_id)
    shaped = [_shape_third_party_audit_entry(r) for r in history_rows]
    return {"claim_id": claim_id, "history": shaped, "history_total": history_total}


@router.post("/claims/{claim_id}/documents")
async def upload_third_party_portal_document(
    claim_id: str,
    file: UploadFile = File(...),
    document_type: Optional[str] = Query(None),
    tp_ctx: ThirdPartyPortalContext = Depends(_tp_ctx_dep),
):
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
            raise HTTPException(status_code=413, detail="File exceeds maximum upload size")
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
        received_from="third_party",
    )
    _maybe_update_document_request_on_receipt(doc_repo, repo, claim_id, doc_type)
    doc = doc_repo.get_document(doc_id)
    if doc:
        doc["url"] = storage.get_url(claim_id, stored_key)
        if isinstance(storage, S3StorageAdapter):
            repo.insert_document_accessed_audit(
                claim_id,
                storage_key=stored_key,
                actor_id=tp_ctx.identity,
                channel="third_party_portal",
            )
    return {"claim_id": claim_id, "document_id": doc_id, "document": doc}


@router.get("/claims/{claim_id}/attachments/{key}")
def get_third_party_portal_attachment(
    claim_id: str,
    key: str,
    tp_ctx: ThirdPartyPortalContext = Depends(_tp_ctx_dep),
):
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

    repo.insert_document_download_audit(
        claim_id,
        storage_key=key,
        actor_id=tp_ctx.identity,
        channel="third_party_portal",
    )
    return FileResponse(path=str(file_path), filename=key)


@router.post("/claims/{claim_id}/follow-up/record-response")
def record_third_party_portal_follow_up_response(
    claim_id: str,
    body: RecordFollowUpResponseBody = Body(...),
    tp_ctx: ThirdPartyPortalContext = Depends(_tp_ctx_dep),
):
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    msg = repo.get_follow_up_message_by_id(body.message_id)
    if msg is None:
        raise HTTPException(status_code=400, detail=f"Follow-up message not found: {body.message_id}")
    if msg.get("claim_id") != claim_id:
        raise HTTPException(
            status_code=400,
            detail=f"Follow-up message {body.message_id} does not belong to claim {claim_id}",
        )
    if msg.get("user_type") != "other":
        raise HTTPException(
            status_code=400,
            detail="This message is not addressed to the third-party portal",
        )
    try:
        repo.record_follow_up_response(
            body.message_id,
            body.response_content,
            actor_id=tp_ctx.identity,
            expected_claim_id=claim_id,
        )
        return {"success": True, "message": "Response recorded"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/claims/{claim_id}/dispute")
async def file_third_party_portal_dispute(
    claim_id: str,
    body: DisputeBody = Body(...),
    tp_ctx: ThirdPartyPortalContext = Depends(_tp_ctx_dep),
):
    """File a dispute (e.g. liability) as a verified third party (not adjuster API)."""
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
        "dispute_description": (
            f"[Third-party portal — {tp_ctx.identity}] {body.dispute_description}"
        ),
        "policyholder_evidence": body.policyholder_evidence,
    }

    result = await asyncio.to_thread(
        run_dispute_workflow,
        dispute_data,
        ctx=ctx,
    )
    return result
