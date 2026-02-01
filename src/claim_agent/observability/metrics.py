"""Cost and latency metrics tracking per claim.

This module provides:
- ClaimMetrics: Aggregates metrics per claim
- Cost tracking with model-specific pricing
- Latency percentile calculations
- Export to various formats (JSON, dict)
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Model pricing per 1K tokens (approximate, update as needed)
# Format: model_name -> (input_price, output_price) per 1K tokens
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI models
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    # Claude models
    "claude-3-opus": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-3.5-sonnet": (0.003, 0.015),
    # OpenRouter variants
    "openrouter/openai/gpt-4o-mini": (0.00015, 0.0006),
    "openrouter/openai/gpt-4o": (0.005, 0.015),
    "openrouter/anthropic/claude-3-sonnet": (0.003, 0.015),
}

# Default pricing if model not found
DEFAULT_PRICING = (0.001, 0.002)  # $0.001/$0.002 per 1K tokens


@dataclass
class LLMCallMetric:
    """Metrics for a single LLM call."""

    timestamp: datetime
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    status: str
    error: str | None = None
    agent: str | None = None
    task: str | None = None


@dataclass
class ClaimMetricsSummary:
    """Summary of metrics for a single claim."""

    claim_id: str
    start_time: datetime
    end_time: datetime | None
    total_llm_calls: int
    successful_calls: int
    failed_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    total_latency_ms: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    models_used: list[str]
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "claim_id": self.claim_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_llm_calls": self.total_llm_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "models_used": self.models_used,
            "status": self.status,
        }


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost for a given model and token counts.

    Args:
        model: Model name/identifier
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens

    Returns:
        Estimated cost in USD
    """
    # Try exact match first
    if model in MODEL_PRICING:
        input_price, output_price = MODEL_PRICING[model]
    else:
        # Try to find a partial match
        model_lower = model.lower()
        matched_pricing = None
        for key, pricing in MODEL_PRICING.items():
            if key.lower() in model_lower or model_lower in key.lower():
                matched_pricing = pricing
                break
        if matched_pricing:
            input_price, output_price = matched_pricing
        else:
            input_price, output_price = DEFAULT_PRICING

    cost = (input_tokens * input_price / 1000) + (output_tokens * output_price / 1000)
    return cost


def _percentile(values: list[float], p: float) -> float:
    """Calculate the p-th percentile of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[-1]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


class ClaimMetrics:
    """Collects and aggregates metrics for claim processing.

    Thread-safe metrics collector that tracks:
    - LLM calls per claim
    - Token usage and costs
    - Latency statistics
    - Error rates
    """

    def __init__(self):
        # Use RLock (reentrant lock) to allow nested lock acquisition
        self._lock = threading.RLock()
        self._claims: dict[str, dict[str, Any]] = {}
        self._global_metrics: list[LLMCallMetric] = []

    def start_claim(self, claim_id: str) -> None:
        """Mark the start of claim processing."""
        with self._lock:
            if claim_id not in self._claims:
                self._claims[claim_id] = {
                    "start_time": datetime.now(timezone.utc),
                    "end_time": None,
                    "llm_calls": [],
                    "status": "processing",
                }
            logger.debug("Started tracking claim: %s", claim_id)

    def end_claim(self, claim_id: str, status: str = "completed") -> None:
        """Mark the end of claim processing."""
        with self._lock:
            if claim_id in self._claims:
                self._claims[claim_id]["end_time"] = datetime.now(timezone.utc)
                self._claims[claim_id]["status"] = status
            logger.debug("Finished tracking claim: %s with status: %s", claim_id, status)

    def record_llm_call(
        self,
        claim_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None = None,
        latency_ms: float = 0.0,
        status: str = "success",
        error: str | None = None,
        agent: str | None = None,
        task: str | None = None,
    ) -> None:
        """Record an LLM call metric.

        Args:
            claim_id: ID of the claim being processed
            model: Model name/identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cost_usd: Cost in USD (calculated if not provided)
            latency_ms: Latency in milliseconds
            status: "success" or "error"
            error: Error message if status is "error"
            agent: Agent name (optional)
            task: Task name (optional)
        """
        # Calculate cost if not provided
        if cost_usd is None:
            cost_usd = calculate_cost(model, input_tokens, output_tokens)

        metric = LLMCallMetric(
            timestamp=datetime.now(timezone.utc),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            error=error,
            agent=agent,
            task=task,
        )

        with self._lock:
            # Ensure claim exists
            if claim_id not in self._claims:
                self.start_claim(claim_id)

            self._claims[claim_id]["llm_calls"].append(metric)
            self._global_metrics.append(metric)

        # Log the metric
        logger.info(
            "[llm_metric] claim_id=%s, model=%s, tokens=%d/%d, cost=$%.4f, latency=%.0fms, status=%s",
            claim_id,
            model,
            input_tokens,
            output_tokens,
            cost_usd,
            latency_ms,
            status,
        )

    def get_claim_summary(self, claim_id: str) -> ClaimMetricsSummary | None:
        """Get summary metrics for a specific claim."""
        with self._lock:
            if claim_id not in self._claims:
                return None

            claim_data = self._claims[claim_id]
            calls: list[LLMCallMetric] = claim_data["llm_calls"]

            if not calls:
                return ClaimMetricsSummary(
                    claim_id=claim_id,
                    start_time=claim_data["start_time"],
                    end_time=claim_data["end_time"],
                    total_llm_calls=0,
                    successful_calls=0,
                    failed_calls=0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_tokens=0,
                    total_cost_usd=0.0,
                    total_latency_ms=0.0,
                    avg_latency_ms=0.0,
                    p50_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    p99_latency_ms=0.0,
                    models_used=[],
                    status=claim_data["status"],
                )

            latencies = [c.latency_ms for c in calls]
            models = list(set(c.model for c in calls))
            total_input = sum(c.input_tokens for c in calls)
            total_output = sum(c.output_tokens for c in calls)
            total_cost = sum(c.cost_usd for c in calls)
            total_latency = sum(latencies)
            successful = len([c for c in calls if c.status == "success"])
            failed = len([c for c in calls if c.status == "error"])

            return ClaimMetricsSummary(
                claim_id=claim_id,
                start_time=claim_data["start_time"],
                end_time=claim_data["end_time"],
                total_llm_calls=len(calls),
                successful_calls=successful,
                failed_calls=failed,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                total_tokens=total_input + total_output,
                total_cost_usd=total_cost,
                total_latency_ms=total_latency,
                avg_latency_ms=total_latency / len(calls) if calls else 0.0,
                p50_latency_ms=_percentile(latencies, 50),
                p95_latency_ms=_percentile(latencies, 95),
                p99_latency_ms=_percentile(latencies, 99),
                models_used=models,
                status=claim_data["status"],
            )

    def get_all_summaries(self) -> list[ClaimMetricsSummary]:
        """Get summaries for all tracked claims."""
        with self._lock:
            claim_ids = list(self._claims.keys())

        return [s for s in (self.get_claim_summary(cid) for cid in claim_ids) if s]

    def get_global_stats(self) -> dict[str, Any]:
        """Get global statistics across all claims."""
        summaries = self.get_all_summaries()

        if not summaries:
            return {
                "total_claims": 0,
                "total_llm_calls": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "avg_cost_per_claim": 0.0,
                "avg_tokens_per_claim": 0.0,
                "avg_latency_per_claim_ms": 0.0,
            }

        return {
            "total_claims": len(summaries),
            "total_llm_calls": sum(s.total_llm_calls for s in summaries),
            "total_tokens": sum(s.total_tokens for s in summaries),
            "total_cost_usd": sum(s.total_cost_usd for s in summaries),
            "avg_cost_per_claim": sum(s.total_cost_usd for s in summaries) / len(summaries),
            "avg_tokens_per_claim": sum(s.total_tokens for s in summaries) / len(summaries),
            "avg_latency_per_claim_ms": (
                sum(s.total_latency_ms for s in summaries) / len(summaries)
            ),
        }

    def export_json(self, claim_id: str | None = None) -> str:
        """Export metrics as JSON.

        Args:
            claim_id: If provided, export only this claim's metrics.
                     Otherwise, export all metrics.

        Returns:
            JSON string
        """
        if claim_id:
            summary = self.get_claim_summary(claim_id)
            if not summary:
                return json.dumps({"error": f"Claim not found: {claim_id}"})
            return json.dumps(summary.to_dict(), indent=2, default=str)
        else:
            return json.dumps(
                {
                    "global_stats": self.get_global_stats(),
                    "claims": [s.to_dict() for s in self.get_all_summaries()],
                },
                indent=2,
                default=str,
            )

    def log_claim_summary(self, claim_id: str) -> None:
        """Log a summary of the claim's metrics."""
        summary = self.get_claim_summary(claim_id)
        if not summary:
            logger.warning("No metrics found for claim: %s", claim_id)
            return

        logger.info(
            "[claim_metrics_summary] claim_id=%s, llm_calls=%d, tokens=%d, "
            "cost=$%.4f, total_latency=%.0fms, avg_latency=%.0fms, status=%s",
            claim_id,
            summary.total_llm_calls,
            summary.total_tokens,
            summary.total_cost_usd,
            summary.total_latency_ms,
            summary.avg_latency_ms,
            summary.status,
        )


# Global metrics instance
_global_metrics: ClaimMetrics | None = None
_metrics_lock = threading.Lock()


def get_metrics() -> ClaimMetrics:
    """Get the global ClaimMetrics instance."""
    global _global_metrics
    with _metrics_lock:
        if _global_metrics is None:
            _global_metrics = ClaimMetrics()
        return _global_metrics


def track_llm_call(
    claim_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None = None,
    latency_ms: float = 0.0,
    status: str = "success",
    error: str | None = None,
) -> None:
    """Convenience function to track an LLM call on the global metrics instance."""
    get_metrics().record_llm_call(
        claim_id=claim_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        status=status,
        error=error,
    )


def get_claim_summary(claim_id: str) -> ClaimMetricsSummary | None:
    """Convenience function to get claim summary from global metrics."""
    return get_metrics().get_claim_summary(claim_id)
