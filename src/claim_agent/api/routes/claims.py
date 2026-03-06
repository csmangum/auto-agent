"""Claims API routes: listing, detail, audit log, workflow runs, statistics, async submit."""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.constants import STATUS_PENDING, STATUS_QUEUED
from claim_agent.db.database import get_connection
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.queue import (
    enqueue_claim_job,
    get_job_id_for_claim,
    get_job_status,
    is_queue_available,
)
from claim_agent.utils.sanitization import sanitize_claim_data

router = APIRouter(tags=["claims"])


@router.post("/claims")
def submit_claim(
    body: ClaimInput,
    async_mode: bool = Query(True, alias="async", description="If true, enqueue and return 202; if false, process synchronously"),
):
    """Submit a claim for processing.

    - **async=true** (default): Returns 202 with job_id and claim_id; processing runs in background.
      Requires REDIS_URL to be configured.
    - **async=false**: Processes synchronously, returns 200 with full result.
    """
    sanitized = sanitize_claim_data(body.model_dump(mode="json"))
    claim_data = ClaimInput.model_validate(sanitized).model_dump(mode="json")

    if async_mode:
        if not is_queue_available():
            raise HTTPException(
                status_code=503,
                detail="Async processing requires REDIS_URL. Set REDIS_URL or use ?async=false for sync.",
            )
        repo = ClaimRepository()
        claim_id = repo.create_claim(ClaimInput.model_validate(claim_data), initial_status=STATUS_QUEUED)
        job_id = enqueue_claim_job(claim_data, claim_id)
        if job_id is None:
            repo.update_claim_status(claim_id, STATUS_PENDING)  # Fallback if enqueue failed
            raise HTTPException(status_code=503, detail="Failed to enqueue job")
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "claim_id": claim_id,
                "message": "Claim queued for processing. Poll GET /api/jobs/{job_id} for status.",
            },
        )

    # Sync mode
    result = run_claim_workflow(claim_data)
    return result


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Poll job status: pending, running, completed, failed."""
    status = get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return status


@router.get("/claims/{claim_id}/job")
def get_claim_job(claim_id: str):
    """Get job info for a claim (if submitted async)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    job_id = get_job_id_for_claim(claim_id)
    if job_id is None:
        return {"claim_id": claim_id, "job_id": None, "message": "Claim was not submitted via async queue"}
    status = get_job_status(job_id)
    return {"claim_id": claim_id, "job_id": job_id, **status}


@router.post("/claims/batch")
def submit_claims_batch(body: list[dict[str, Any]]):
    """Submit multiple claims for async processing. Returns list of job_ids and claim_ids.

    Requires REDIS_URL. All claims are processed in background.
    """
    if not is_queue_available():
        raise HTTPException(
            status_code=503,
            detail="Batch processing requires REDIS_URL. Configure Redis and restart.",
        )
    results = []
    for i, item in enumerate(body):
        try:
            claim_input = ClaimInput.model_validate(item)
        except ValidationError as e:
            results.append({"index": i, "error": str(e.errors()), "job_id": None, "claim_id": None})
            continue
        sanitized = sanitize_claim_data(claim_input.model_dump(mode="json"))
        claim_data = ClaimInput.model_validate(sanitized).model_dump(mode="json")
        repo = ClaimRepository()
        claim_id = repo.create_claim(ClaimInput.model_validate(claim_data), initial_status=STATUS_QUEUED)
        job_id = enqueue_claim_job(claim_data, claim_id)
        if job_id is None:
            repo.update_claim_status(claim_id, STATUS_PENDING)
        results.append({
            "index": i,
            "job_id": job_id,
            "claim_id": claim_id,
            "error": None if job_id else "Failed to enqueue",
        })
    return JSONResponse(status_code=202, content={"jobs": results})


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
    with get_connection() as conn:
        # Verify claim exists
        claim = conn.execute(
            "SELECT id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if claim is None:
            raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

        rows = conn.execute(
            "SELECT * FROM claim_audit_log WHERE claim_id = ? ORDER BY id ASC",
            (claim_id,),
        ).fetchall()

    return {"claim_id": claim_id, "history": [dict(r) for r in rows]}


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
