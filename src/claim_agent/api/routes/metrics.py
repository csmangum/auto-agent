"""Metrics API routes: global and per-claim observability metrics."""

from fastapi import APIRouter, HTTPException

from claim_agent.observability import get_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_global_metrics():
    """Get global metrics summary across all claims.

    Note: Metrics are in-memory and only populated during claim processing
    in the current server process. Returns zero/empty when no claims have
    been processed since server start.
    """
    metrics = get_metrics()
    global_stats = metrics.get_global_stats()
    summaries = metrics.get_all_summaries()

    return {
        "global_stats": global_stats,
        "claims": [s.to_dict() for s in summaries],
    }


@router.get("/metrics/{claim_id}")
async def get_claim_metrics(claim_id: str):
    """Get metrics for a specific claim."""
    metrics = get_metrics()
    summary = metrics.get_claim_summary(claim_id)

    if summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"No metrics found for claim: {claim_id}. "
            "Metrics are only available for claims processed in the current session.",
        )

    return summary.to_dict()
