"""Async job queue for claim processing.

Uses Redis + RQ when REDIS_URL is configured. Enables:
- POST /claims returning 202 with job_id
- Background processing via worker process
- Poll GET /jobs/{job_id} for status
"""

from claim_agent.queue.queue import (
    enqueue_claim_job,
    get_job_id_for_claim,
    get_job_status,
    get_queue,
    is_queue_available,
)

__all__ = [
    "enqueue_claim_job",
    "get_job_id_for_claim",
    "get_job_status",
    "get_queue",
    "is_queue_available",
]
