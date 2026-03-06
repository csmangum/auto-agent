"""Claims API routes: listing, detail, audit log, workflow runs, statistics."""

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from claim_agent.db.audit_events import ACTOR_SYSTEM
from claim_agent.db.database import get_connection, get_db_path
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import Attachment
from claim_agent.storage import get_storage_adapter
from claim_agent.utils import infer_attachment_type

router = APIRouter(tags=["claims"])

_MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


@router.get("/claims/stats")
def get_claims_stats():
    """Aggregate statistics: count by status, count by type, totals."""
    with get_connection() as conn:
        # Total count
        total = conn.execute("SELECT COUNT(*) as cnt FROM claims").fetchone()["cnt"]

        # By status
        rows = conn.execute(
            "SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt "
            "FROM claims GROUP BY status ORDER BY cnt DESC"
        ).fetchall()
        by_status = {r["status"]: r["cnt"] for r in rows}

        # By type
        rows = conn.execute(
            "SELECT COALESCE(claim_type, 'unclassified') as claim_type, COUNT(*) as cnt "
            "FROM claims GROUP BY claim_type ORDER BY cnt DESC"
        ).fetchall()
        by_type = {r["claim_type"]: r["cnt"] for r in rows}

        # Date range
        date_row = conn.execute(
            "SELECT MIN(created_at) as earliest, MAX(created_at) as latest FROM claims"
        ).fetchone()

        # Recent audit events count
        audit_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM claim_audit_log"
        ).fetchone()["cnt"]

        # Workflow runs count
        workflow_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM workflow_runs"
        ).fetchone()["cnt"]

    return {
        "total_claims": total,
        "by_status": by_status,
        "by_type": by_type,
        "earliest_claim": date_row["earliest"],
        "latest_claim": date_row["latest"],
        "total_audit_events": audit_count,
        "total_workflow_runs": workflow_count,
    }


@router.get("/claims")
def list_claims(
    status: Optional[str] = Query(None, description="Filter by status"),
    claim_type: Optional[str] = Query(None, description="Filter by claim type"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List claims with optional filtering."""
    conditions = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if claim_type:
        conditions.append("claim_type = ?")
        params.append(claim_type)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        # Get total for pagination
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM claims {where}", params
        ).fetchone()
        total = count_row["cnt"]

        rows = conn.execute(
            f"SELECT * FROM claims {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "claims": [dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str):
    """Get a single claim by ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    return dict(row)


@router.get("/claims/{claim_id}/history")
def get_claim_history(claim_id: str):
    """Get audit log entries for a claim."""
    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    history = repo.get_claim_history(claim_id)
    return {"claim_id": claim_id, "history": history}


@router.get("/claims/{claim_id}/workflows")
def get_claim_workflows(claim_id: str):
    """Get workflow runs for a claim."""
    with get_connection() as conn:
        # Verify claim exists
        claim = conn.execute(
            "SELECT id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if claim is None:
            raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

        rows = conn.execute(
            "SELECT * FROM workflow_runs WHERE claim_id = ? ORDER BY id ASC",
            (claim_id,),
        ).fetchall()

    return {"claim_id": claim_id, "workflows": [dict(r) for r in rows]}


@router.post("/claims/process")
async def process_claim(
    claim: str = Form(..., description="Claim data as JSON string"),
    files: list[UploadFile] = File(default=[], description="Optional attachment files"),
):
    """Submit a new claim for processing. Accepts claim JSON and optional file uploads.

    - claim: JSON string with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
      incident_date, incident_description, damage_description, estimated_damage (optional),
      attachments (optional list of {url, type, description}).
    - files: Optional multipart files (photos, PDFs, estimates). Stored via configured backend.
    """
    try:
        claim_data = json.loads(claim)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim JSON: {e}") from e

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.utils.sanitization import sanitize_claim_data

    sanitized = sanitize_claim_data(claim_data)
    try:
        from claim_agent.models.claim import ClaimInput

        claim_input = ClaimInput.model_validate(sanitized)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data: {e}") from e

    repo = ClaimRepository(db_path=get_db_path())

    # Validate and buffer all file uploads BEFORE creating the claim record so
    # that a bad upload (oversized or empty) does not leave a dangling claim row.
    buffered_files: list[tuple[str, bytes, str | None]] = []
    if files:
        for f in files:
            if not f.filename:
                continue
            # Read in bounded chunks to enforce the size limit without loading
            # an arbitrarily large file into memory.
            chunks: list[bytes] = []
            total_size = 0
            chunk_size = 1024 * 1024  # 1 MB
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > _MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{f.filename}' exceeds the maximum upload size of {_MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
                    )
                chunks.append(chunk)
            buffered_files.append((f.filename, b"".join(chunks), f.content_type))

    claim_id = repo.create_claim(claim_input)

    # Store uploaded files now that the claim record exists.
    all_attachments = list(claim_input.attachments)
    if buffered_files:
        storage = get_storage_adapter()
        for filename, content, content_type in buffered_files:
            stored_key = storage.save(
                claim_id=claim_id,
                filename=filename,
                content=content,
                content_type=content_type,
            )
            url = storage.get_url(claim_id, stored_key)
            atype = infer_attachment_type(filename)
            all_attachments.append(
                Attachment(url=url, type=atype, description=f"Uploaded: {filename}")
            )
        if all_attachments:
            repo.update_claim_attachments(claim_id, all_attachments, actor_id=ACTOR_SYSTEM)

    # Run workflow with updated claim data (including attachment URLs)
    claim_data_with_attachments = {**sanitized, "attachments": [a.model_dump(mode="json") for a in all_attachments]}
    result = run_claim_workflow(claim_data_with_attachments, existing_claim_id=claim_id)
    return result
