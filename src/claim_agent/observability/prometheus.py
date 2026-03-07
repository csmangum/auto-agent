"""Prometheus metrics export for production observability."""

from __future__ import annotations

import threading

from claim_agent.db.constants import STATUS_NEEDS_REVIEW, STATUS_PROCESSING
from claim_agent.db.database import get_connection
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)

# Statuses that count as successful processing (not failed, not escalated)
_PROCESSED_STATUSES = frozenset(
    {"open", "closed", "settled", "duplicate", "fraud_suspected"}
)

_claims_processed_total: Counter | None = None
_claims_failed_total: Counter | None = None
_claims_escalated_total: Counter | None = None
_claim_processing_duration_seconds: Histogram | None = None
_llm_tokens_total: Counter | None = None
_claims_in_progress: Gauge | None = None
_review_queue_size: Gauge | None = None
_metrics_lock = threading.Lock()


def _ensure_metrics() -> None:
    """Lazily create Prometheus metrics on first use."""
    global _claims_processed_total, _claims_failed_total, _claims_escalated_total
    global _claim_processing_duration_seconds, _llm_tokens_total
    global _claims_in_progress, _review_queue_size

    if _claims_processed_total is not None:
        return

    with _metrics_lock:
        if _claims_processed_total is not None:
            return

        _claims_processed_total = Counter(
            "claims_processed_total",
            "Total number of claims successfully processed",
        )
        _claims_failed_total = Counter(
            "claims_failed_total",
            "Total number of claims that failed processing",
        )
        _claims_escalated_total = Counter(
            "claims_escalated_total",
            "Total number of claims escalated to human review",
        )
        _claim_processing_duration_seconds = Histogram(
            "claim_processing_duration_seconds",
            "Claim processing duration in seconds",
            buckets=(1, 5, 10, 30, 60, 120, 300),
        )
        _llm_tokens_total = Counter(
            "llm_tokens_total",
            "Total LLM tokens used",
            ["type"],
        )
        _claims_in_progress = Gauge(
            "claims_in_progress",
            "Number of claims currently being processed",
        )
        _review_queue_size = Gauge(
            "review_queue_size",
            "Number of claims in the review queue (needs_review)",
        )


def record_claim_outcome(
    claim_id: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record a claim processing outcome for Prometheus.

    Call after metrics.end_claim() with the same status.

    Args:
        claim_id: Claim ID (for logging; not used in metrics)
        status: End status: "error", "escalated", or a success status
        duration_seconds: Workflow duration in seconds
    """
    _ensure_metrics()
    if _claims_processed_total is None:
        return

    if status == "error":
        _claims_failed_total.inc()
    elif status == "escalated":
        _claims_escalated_total.inc()
    elif status in _PROCESSED_STATUSES:
        _claims_processed_total.inc()

    if _claim_processing_duration_seconds is not None and duration_seconds >= 0:
        _claim_processing_duration_seconds.observe(duration_seconds)


def record_llm_tokens(input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage for Prometheus.

    Call from record_llm_call in metrics.py.

    Args:
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
    """
    _ensure_metrics()
    if _llm_tokens_total is None:
        return

    if input_tokens > 0:
        _llm_tokens_total.labels(type="input").inc(input_tokens)
    if output_tokens > 0:
        _llm_tokens_total.labels(type="output").inc(output_tokens)


def _update_gauges() -> None:
    """Query DB and update gauge metrics. Call before generate_metrics()."""
    _ensure_metrics()
    if _claims_in_progress is None or _review_queue_size is None:
        return

    try:
        with get_connection() as conn:
            in_progress = conn.execute(
                "SELECT COUNT(*) as cnt FROM claims WHERE status = ?",
                (STATUS_PROCESSING,),
            ).fetchone()["cnt"]
            review = conn.execute(
                "SELECT COUNT(*) as cnt FROM claims WHERE status = ?",
                (STATUS_NEEDS_REVIEW,),
            ).fetchone()["cnt"]
            _claims_in_progress.set(in_progress)
            _review_queue_size.set(review)
    except Exception:
        _claims_in_progress.set(-1)
        _review_queue_size.set(-1)


def generate_metrics() -> bytes:
    """Generate Prometheus text format. Updates gauges from DB before export."""
    _ensure_metrics()
    _update_gauges()
    return generate_latest(REGISTRY)
