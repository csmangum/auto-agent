"""Document and attachment routes for claims."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import require_role
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.document_repository import build_document_version_groups
from claim_agent.models.document import DocumentRequestStatus, DocumentType, ReviewStatus
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.api.routes._claims_helpers import (
    ALLOWED_DOCUMENT_EXTENSIONS as _ALLOWED_DOCUMENT_EXTENSIONS,
    VALID_DOCUMENT_TYPES as _VALID_DOCUMENT_TYPES,
    get_claim_context,
    get_doc_repo as _get_doc_repo,
    max_upload_file_size_bytes as _max_upload_file_size_bytes,
    maybe_update_document_request_on_receipt as _maybe_update_document_request_on_receipt,
    upload_file_size_exceeded_detail as _upload_file_size_exceeded_detail,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


@router.get("/claims/{claim_id}/attachments/{key}", dependencies=[RequireAdjuster])
def get_claim_attachment(
    claim_id: str,
    key: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Serve an attachment file for a claim. Local storage only; S3 uses presigned URLs.

    Appends a ``document_downloaded`` row to ``claim_audit_log`` (chain of custody).
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

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

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    ctx.repo.insert_document_download_audit(
        claim_id,
        storage_key=key,
        actor_id=actor_id,
        channel="adjuster_api",
    )
    return FileResponse(path=str(file_path), filename=key)


@router.get("/claims/{claim_id}/documents", dependencies=[RequireAdjuster])
def list_claim_documents(
    claim_id: str,
    document_type: Optional[str] = Query(None, description="Filter by document_type"),
    review_status: Optional[str] = Query(None, description="Filter by review_status"),
    group_by: Optional[str] = Query(
        None,
        description=(
            "If 'storage_key', response includes version_groups built from the first 500 matching "
            "rows (see version_groups_truncated when total exceeds 500)"
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List documents for a claim with optional filters."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    gb = (group_by or "").strip().lower()
    if gb and gb != "storage_key":
        raise HTTPException(
            status_code=400,
            detail="Invalid group_by. Supported value: storage_key",
        )
    doc_repo = _get_doc_repo()
    documents, total = doc_repo.list_documents(
        claim_id, document_type=document_type, review_status=review_status, limit=limit, offset=offset
    )
    storage = get_storage_adapter()
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW

    def enrich_document_urls(docs: list[dict[str, Any]], insert_audit: bool = True) -> None:
        for doc in docs:
            sk = doc.get("storage_key", "")
            if sk:
                doc["url"] = storage.get_url(claim_id, sk)
                if insert_audit and isinstance(storage, S3StorageAdapter):
                    ctx.repo.insert_document_accessed_audit(
                        claim_id,
                        storage_key=sk,
                        actor_id=actor_id,
                        channel="adjuster_api",
                    )
            else:
                doc["url"] = None

    enrich_document_urls(documents)
    payload: dict[str, Any] = {
        "claim_id": claim_id,
        "documents": documents,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    if gb == "storage_key":
        all_docs, docs_total = doc_repo.list_documents(
            claim_id,
            document_type=document_type,
            review_status=review_status,
            limit=500,
            offset=0,
        )
        enrich_document_urls(all_docs, insert_audit=False)
        payload["version_groups"] = build_document_version_groups(all_docs)
        payload["version_groups_truncated"] = docs_total > 500
    return payload


@router.post("/claims/{claim_id}/documents", dependencies=[RequireAdjuster])
async def upload_claim_document(
    claim_id: str,
    file: UploadFile = File(...),
    document_type: Optional[str] = Query(None, description="Document type (police_report, estimate, etc.)"),
    received_from: Optional[str] = Query(None, description="Source (claimant, repair_shop, etc.)"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Upload a document and create a claim_documents record."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
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
    doc_type = document_type or attachment_type_to_document_type(infer_attachment_type(file.filename)).value
    if doc_type not in _VALID_DOCUMENT_TYPES:
        doc_type = DocumentType.OTHER.value
    doc_repo = _get_doc_repo()
    doc_id = doc_repo.add_document(
        claim_id,
        stored_key,
        document_type=doc_type,
        received_from=received_from or "claimant",
    )
    _maybe_update_document_request_on_receipt(doc_repo, ctx.repo, claim_id, doc_type)
    doc = doc_repo.get_document(doc_id)
    if doc:
        doc["url"] = storage.get_url(claim_id, stored_key)
        if isinstance(storage, S3StorageAdapter):
            actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
            ctx.repo.insert_document_accessed_audit(
                claim_id,
                storage_key=stored_key,
                actor_id=actor_id,
                channel="adjuster_api",
            )
    return {"claim_id": claim_id, "document_id": doc_id, "document": doc}


class DocumentUpdateBody(BaseModel):
    """Body for PATCH /claims/{claim_id}/documents/{doc_id}."""

    review_status: Optional[str] = None
    document_type: Optional[str] = None
    privileged: Optional[bool] = None
    retention_date: Optional[str] = None


@router.patch("/claims/{claim_id}/documents/{doc_id}", dependencies=[RequireAdjuster])
def update_claim_document(
    claim_id: str,
    doc_id: int,
    body: DocumentUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update document metadata (review_status, privileged, etc.)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    doc_repo = _get_doc_repo()
    doc = doc_repo.get_document(doc_id)
    if doc is None or doc.get("claim_id") != claim_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    review: ReviewStatus | None = None
    if body.review_status is not None:
        try:
            review = ReviewStatus(body.review_status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid review_status. Must be one of: {[s.value for s in ReviewStatus]}",
            )
    if body.document_type is not None and body.document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {sorted(_VALID_DOCUMENT_TYPES)}",
        )
    updated = doc_repo.update_document_review(
        doc_id,
        review_status=review,
        document_type=body.document_type,
        privileged=body.privileged,
        retention_date=body.retention_date,
    )
    return {"claim_id": claim_id, "document_id": doc_id, "document": updated}


@router.get("/claims/{claim_id}/document-requests", dependencies=[RequireAdjuster])
def list_document_requests(
    claim_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List document requests for a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    doc_repo = _get_doc_repo()
    requests, total = doc_repo.list_document_requests(
        claim_id, status=status, limit=limit, offset=offset
    )
    return {"claim_id": claim_id, "requests": requests, "total": total, "limit": limit, "offset": offset}


class DocumentRequestCreateBody(BaseModel):
    """Body for POST /claims/{claim_id}/document-requests."""

    document_type: str = Field(..., min_length=1, description="Type requested (police_report, estimate, etc.)")
    requested_from: Optional[str] = Field(default=None, description="Party to request from")


@router.post("/claims/{claim_id}/document-requests", dependencies=[RequireAdjuster])
def create_document_request(
    claim_id: str,
    body: DocumentRequestCreateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a document request."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    if body.document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {sorted(_VALID_DOCUMENT_TYPES)}",
        )
    doc_repo = _get_doc_repo()
    req_id = doc_repo.create_document_request(
        claim_id, body.document_type, requested_from=body.requested_from
    )
    req = doc_repo.get_document_request(req_id)
    return {"claim_id": claim_id, "request_id": req_id, "request": req}


class DocumentRequestUpdateBody(BaseModel):
    """Body for PATCH /claims/{claim_id}/document-requests/{req_id}."""

    status: Optional[str] = None
    received_at: Optional[str] = None


@router.patch("/claims/{claim_id}/document-requests/{req_id}", dependencies=[RequireAdjuster])
def update_document_request(
    claim_id: str,
    req_id: int,
    body: DocumentRequestUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update document request (e.g. mark received)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    doc_repo = _get_doc_repo()
    req = doc_repo.get_document_request(req_id)
    if req is None or req.get("claim_id") != claim_id:
        raise HTTPException(status_code=404, detail=f"Document request not found: {req_id}")
    status: DocumentRequestStatus | None = None
    if body.status is not None:
        try:
            status = DocumentRequestStatus(body.status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {[s.value for s in DocumentRequestStatus]}",
            )
    updated = doc_repo.update_document_request(
        req_id, status=status, received_at=body.received_at
    )
    return {"claim_id": claim_id, "request_id": req_id, "request": updated}
