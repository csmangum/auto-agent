"""RQ task definitions for async claim processing."""

import os
from typing import Any

from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.constants import STATUS_PROCESSING
from claim_agent.db.repository import ClaimRepository
from claim_agent.queue.queue import _update_job_status
from claim_agent.utils.retry import with_llm_retry


def _get_current_job_id() -> str | None:
    """Get current RQ job ID from worker context."""
    try:
        from rq import get_current_job

        job = get_current_job()
        return job.id if job else None
    except Exception:
        return None


def process_claim_task(claim_data: dict, claim_id: str) -> dict[str, Any]:
    """Process a claim in the background. Called by RQ worker.

    Retries on transient LLM failures. Updates job status on completion/failure.

    Args:
        claim_data: Sanitized claim payload
        claim_id: Pre-created claim ID (status=queued)

    Returns:
        Workflow result dict (claim_id, claim_type, summary, etc.)
    """
    # Ensure DB path is set for worker process
    if "CLAIMS_DB_PATH" not in os.environ:
        os.environ.setdefault("CLAIMS_DB_PATH", "data/claims.db")

    job_id = _get_current_job_id()
    if job_id:
        _update_job_status(job_id, "running")

    repo = ClaimRepository()
    if repo.get_claim(claim_id) is None:
        err_msg = f"Claim not found: {claim_id}"
        if job_id:
            _update_job_status(job_id, "failed", result_summary=err_msg)
        raise ValueError(err_msg)

    repo.update_claim_status(claim_id, STATUS_PROCESSING)

    @with_llm_retry(max_attempts=3)
    def _run():
        return run_claim_workflow(claim_data, existing_claim_id=claim_id)

    try:
        result = _run()
        summary = result.get("summary", "") or ""
        if len(summary) > 500:
            summary = summary[:500] + "..."
        if job_id:
            _update_job_status(job_id, "completed", result_summary=summary)
        return result
    except Exception as e:
        err_msg = str(e)
        if len(err_msg) > 500:
            err_msg = err_msg[:500] + "..."
        if job_id:
            _update_job_status(job_id, "failed", result_summary=err_msg)
        raise
