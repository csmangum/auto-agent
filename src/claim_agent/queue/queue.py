"""Redis + RQ job queue for async claim processing."""

import os
from typing import Any

from claim_agent.db.database import get_connection


def _get_redis_url() -> str | None:
    """Return REDIS_URL from env, or None if not configured."""
    url = os.environ.get("REDIS_URL", "").strip()
    return url if url else None


def is_queue_available() -> bool:
    """Return True if Redis queue is configured and reachable."""
    url = _get_redis_url()
    if not url:
        return False
    try:
        from redis import Redis
        from rq import Queue

        conn = Redis.from_url(url)
        conn.ping()
        return True
    except Exception:
        return False


def get_queue(name: str = "claims") -> "Queue | None":
    """Return RQ Queue instance, or None if Redis not configured."""
    url = _get_redis_url()
    if not url:
        return None
    try:
        from redis import Redis
        from rq import Queue

        conn = Redis.from_url(url)
        return Queue(name, connection=conn)
    except Exception:
        return None


def _record_job_claim_mapping(job_id: str, claim_id: str) -> None:
    """Store job_id -> claim_id in jobs table for lookup."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO claim_jobs (job_id, claim_id, status)
            VALUES (?, ?, 'queued')
            """,
            (job_id, claim_id),
        )


def _update_job_status(job_id: str, status: str, result_summary: str | None = None) -> None:
    """Update job status in jobs table."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE claim_jobs SET status = ?, result_summary = ?, updated_at = datetime('now')
            WHERE job_id = ?
            """,
            (status, result_summary, job_id),
        )


def enqueue_claim_job(claim_data: dict, claim_id: str) -> str | None:
    """Enqueue a claim for async processing. Returns job_id or None if queue unavailable.

    Args:
        claim_data: Sanitized claim payload
        claim_id: Pre-created claim ID (status=queued)

    Returns:
        RQ job ID string, or None if queue not available
    """
    queue = get_queue()
    if queue is None:
        return None

    from claim_agent.queue.tasks import process_claim_task

    job = queue.enqueue(
        process_claim_task,
        claim_data,
        claim_id,
        job_timeout="15m",
        failure_ttl=86400,  # Keep failed jobs 24h
        result_ttl=86400,
    )
    _record_job_claim_mapping(job.id, claim_id)
    return job.id


def get_job_id_for_claim(claim_id: str) -> str | None:
    """Get job_id for a claim (if it was submitted async)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT job_id FROM claim_jobs WHERE claim_id = ? ORDER BY created_at DESC LIMIT 1",
            (claim_id,),
        ).fetchone()
    return row["job_id"] if row else None


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Get job status: pending, running, completed, failed.

    Returns dict with: status, claim_id (if known), result (if completed), error (if failed).
    """
    # First check our jobs table for claim_id
    with get_connection() as conn:
        row = conn.execute(
            "SELECT job_id, claim_id, status, result_summary FROM claim_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

    claim_id = row["claim_id"] if row else None
    db_status = row["status"] if row else None

    queue = get_queue()
    if queue is None:
        if row:
            return {
                "job_id": job_id,
                "claim_id": claim_id,
                "status": db_status or "unknown",
                "message": "Queue not available; status from database only",
            }
        return None

    from rq.job import Job

    try:
        job = Job.fetch(job_id, connection=queue.connection)
    except Exception:
        if row:
            return {
                "job_id": job_id,
                "claim_id": claim_id,
                "status": db_status or "unknown",
            }
        return None

    rq_status = job.get_status()
    # Map RQ status to our status
    status = rq_status  # queued, started, finished, failed, deferred, etc.

    out: dict[str, Any] = {
        "job_id": job_id,
        "claim_id": claim_id,
        "status": status,
    }

    if job.is_finished:
        out["status"] = "completed"
        out["result"] = job.result
    elif job.is_failed:
        out["status"] = "failed"
        out["error"] = str(job.exc_info) if job.exc_info else str(job.meta.get("error", "Unknown error"))
    elif job.is_queued or job.is_deferred:
        out["status"] = "pending"
    elif job.is_started:
        out["status"] = "running"

    return out
