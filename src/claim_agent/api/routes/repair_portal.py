"""Repair shop self-service portal API (per-claim magic token and shop user accounts)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from claim_agent.api.repair_portal_deps import (
    RepairShopJWTContext,
    RepairShopPortalContext,
    require_repair_shop_access,
    require_shop_user_jwt,
)
from claim_agent.api.routes.claims import (
    _ALLOWED_DOCUMENT_EXTENSIONS,
    _MAX_UPLOAD_SIZE_BYTES,
    _VALID_DOCUMENT_TYPES,
    _get_doc_repo,
    _maybe_update_document_request_on_receipt,
)
from claim_agent.api.routes.portal import (
    PORTAL_CLAIM_FIELDS,
    RecordFollowUpResponseBody,
    _resolve_portal_attachment_urls,
)
from claim_agent.config import get_settings
from claim_agent.config.settings import get_jwt_access_ttl_seconds
from claim_agent.context import ClaimContext
from claim_agent.db.constants import VALID_REPAIR_STATUSES
from claim_agent.db.database import get_db_path
from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.document import DocumentType
from claim_agent.services.shop_jwt import ShopLoginBody, encode_shop_access_token
from claim_agent.services.supplemental_request import execute_supplemental_request
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type

router = APIRouter(prefix="/repair-portal", tags=["repair-portal"])

_ATTACH_BASE = "/api/repair-portal"


def _repair_shop_ctx_dep(claim_id: str, request: Request) -> RepairShopPortalContext:
    return require_repair_shop_access(request, claim_id)


def _get_claim_repo() -> ClaimRepository:
    return ClaimRepository(db_path=get_db_path())


def _shape_repair_portal_claim(row: dict[str, Any]) -> dict[str, Any]:
    base = {k: row.get(k) for k in PORTAL_CLAIM_FIELDS}
    return _resolve_portal_attachment_urls(base, attachments_api_base=_ATTACH_BASE)


def _shape_repair_portal_audit_entry(row: dict[str, Any]) -> dict[str, Any]:
    """External repair shops: status timeline only (no audit blobs, actor ids, or free-text details)."""
    return {
        "id": row.get("id"),
        "action": row.get("action"),
        "old_status": row.get("old_status"),
        "new_status": row.get("new_status"),
        "created_at": row.get("created_at"),
    }


class RepairStatusUpdateBody(BaseModel):
    status: str = Field(..., min_length=1, max_length=64)
    authorization_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class SupplementalBody(BaseModel):
    supplemental_damage_description: str = Field(..., max_length=2000)


def _infer_shop_and_auth(claim_id: str, claim_repo: ClaimRepository) -> tuple[str, str | None]:
    shop_id, auth_id = "unknown", None
    runs = claim_repo.get_workflow_runs(claim_id, limit=5)
    for run in runs:
        if run.get("claim_type") != "partial_loss":
            continue
        parsed = _parse_partial_loss_workflow_output(run.get("workflow_output") or "")
        if parsed:
            shop_id = str(parsed.get("shop_id", "")).strip() or shop_id
            auth_id = str(parsed.get("authorization_id", "")).strip() or None
            break
    return shop_id, auth_id


@router.post("/auth/login")
def repair_shop_login(body: ShopLoginBody):
    """Authenticate a repair shop user with email and password; returns a JWT access token."""
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
        "expires_in": get_jwt_access_ttl_seconds(),
        "shop_id": user["shop_id"],
    }


# --------------------------------------------------------------------------
# Multi-claim inbox
# --------------------------------------------------------------------------


@router.get("/claims")
def list_repair_portal_claims(
    ctx: RepairShopJWTContext = Depends(require_shop_user_jwt),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return all claims assigned to the authenticated shop (requires shop-user JWT)."""
    shop_repo = RepairShopUserRepository()
    total = shop_repo.count_assignments_for_shop(ctx.shop_id)
    assignments = shop_repo.get_assignments_for_shop(ctx.shop_id, limit=limit, offset=offset)
    claim_repo = _get_claim_repo()
    claim_ids = [str(a["claim_id"]) for a in assignments]
    by_id = claim_repo.get_claims_by_ids(claim_ids)
    claims = []
    for a in assignments:
        row = by_id.get(str(a["claim_id"]))
        if row is not None:
            shaped = _shape_repair_portal_claim(row)
            shaped["assigned_at"] = a.get("assigned_at")
            claims.append(shaped)
    return {
        "shop_id": ctx.shop_id,
        "claims": claims,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/claims/{claim_id}")
def get_repair_portal_claim(
    claim_id: str,
    _ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
):
    repo = _get_claim_repo()
    row = repo.get_claim(claim_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    result = _shape_repair_portal_claim(row)
    result["notes"] = []
    all_follow_ups = repo.get_follow_up_messages(claim_id)
    result["follow_up_messages"] = [
        msg for msg in all_follow_ups if (msg.get("user_type") or "") == "repair_shop"
    ]
    doc_repo = _get_doc_repo()
    requests, _total = doc_repo.list_document_requests(claim_id, limit=200, offset=0)
    result["document_requests"] = requests
    result["tasks"] = []
    result["tasks_total"] = 0
    result["subrogation_cases"] = []
    return result


@router.get("/claims/{claim_id}/history")
def get_repair_portal_claim_history(
    claim_id: str,
    _ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
):
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    history_rows, history_total = repo.get_claim_history(claim_id)
    shaped = [_shape_repair_portal_audit_entry(r) for r in history_rows]
    return {"claim_id": claim_id, "history": shaped, "history_total": history_total}


@router.post("/claims/{claim_id}/follow-up/record-response")
def record_repair_portal_follow_up_response(
    claim_id: str,
    body: RecordFollowUpResponseBody = Body(...),
    ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
):
    """Record the repair shop's response to a follow-up addressed to user_type=repair_shop."""
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
    if msg.get("user_type") != "repair_shop":
        raise HTTPException(
            status_code=400,
            detail="This message is not addressed to the repair shop portal",
        )
    try:
        repo.record_follow_up_response(
            body.message_id,
            body.response_content,
            actor_id=ctx.identity,
            expected_claim_id=claim_id,
        )
        return {"success": True, "message": "Response recorded"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/claims/{claim_id}/repair-status")
def get_repair_portal_repair_status(
    claim_id: str,
    _ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
):
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


@router.post("/claims/{claim_id}/repair-status")
def post_repair_portal_repair_status(
    claim_id: str,
    body: RepairStatusUpdateBody = Body(...),
    ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
):
    if body.status not in VALID_REPAIR_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_REPAIR_STATUSES)}",
        )
    claim_repo = _get_claim_repo()
    claim = claim_repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    if claim.get("claim_type") != "partial_loss":
        raise HTTPException(
            status_code=400,
            detail="Repair status only applies to partial_loss claims",
        )
    shop_id = (ctx.shop_id or "").strip() or None
    auth_id = body.authorization_id
    if not shop_id or not auth_id:
        inferred_shop, inferred_auth = _infer_shop_and_auth(claim_id, claim_repo)
        shop_id = shop_id or inferred_shop
        auth_id = auth_id or inferred_auth
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


@router.get("/claims/{claim_id}/documents")
def list_repair_portal_documents(
    claim_id: str,
    ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
    document_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    repo = _get_claim_repo()
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    doc_repo = _get_doc_repo()
    documents, total = doc_repo.list_documents(
        claim_id, document_type=document_type, review_status=None, limit=limit, offset=offset
    )
    storage = get_storage_adapter()
    actor_id = ctx.identity
    for doc in documents:
        sk = doc.get("storage_key", "")
        if sk:
            doc["url"] = storage.get_url(claim_id, sk)
            if isinstance(storage, S3StorageAdapter):
                repo.insert_document_accessed_audit(
                    claim_id,
                    storage_key=sk,
                    actor_id=actor_id,
                    channel="repair_portal",
                )
        else:
            doc["url"] = None
    return {"claim_id": claim_id, "documents": documents, "total": total, "limit": limit, "offset": offset}


@router.post("/claims/{claim_id}/documents")
async def upload_repair_portal_document(
    claim_id: str,
    ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
    file: UploadFile = File(...),
    document_type: Optional[str] = Query(None),
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
        if total_size > _MAX_UPLOAD_SIZE_BYTES:
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
        received_from="repair_shop",
    )
    _maybe_update_document_request_on_receipt(doc_repo, repo, claim_id, doc_type)
    doc = doc_repo.get_document(doc_id)
    if doc:
        sk = doc.get("storage_key", "")
        if sk:
            doc["url"] = storage.get_url(claim_id, sk)
            if isinstance(storage, S3StorageAdapter):
                repo.insert_document_accessed_audit(
                    claim_id,
                    storage_key=sk,
                    actor_id=ctx.identity,
                    channel="repair_portal",
                )
    return {"claim_id": claim_id, "document_id": doc_id, "document": doc}


@router.get("/claims/{claim_id}/attachments/{key}")
def get_repair_portal_attachment(
    claim_id: str,
    key: str,
    ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
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
        actor_id=ctx.identity,
        channel="repair_portal",
    )
    return FileResponse(path=str(file_path), filename=key)


@router.post("/claims/{claim_id}/supplemental")
async def file_repair_portal_supplemental(
    claim_id: str,
    body: SupplementalBody = Body(...),
    _ctx: RepairShopPortalContext = Depends(_repair_shop_ctx_dep),
):
    ctx = ClaimContext.from_defaults(db_path=get_db_path())
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    try:
        return await execute_supplemental_request(
            claim_id=claim_id,
            supplemental_damage_description=body.supplemental_damage_description,
            reported_by="shop",
            ctx=ctx,
        )
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        msg = str(e)
        code = 409 if "cannot receive supplemental" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from e
