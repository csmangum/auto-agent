"""Cost and latency metrics tracking per claim.

This module provides:
- ClaimMetrics: Aggregates metrics per claim
- Cost tracking with model-specific pricing
- Latency percentile calculations
- Export to various formats (JSON, dict)
"""

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from claim_agent.config.settings import get_llm_cost_alert_config
from claim_agent.observability.prometheus import record_llm_tokens

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
    crew: str | None = None
    claim_type: str | None = None


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
    # Guard against mock objects (e.g. MagicMock in tests)
    if not isinstance(model, str):
        return 0.0
    if not isinstance(input_tokens, (int, float)) or not isinstance(output_tokens, (int, float)):
        return 0.0
    input_tokens = int(input_tokens)
    output_tokens = int(output_tokens)
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

    def __init__(self) -> None:
        # Use RLock (reentrant lock) to allow nested lock acquisition
        self._lock = threading.RLock()
        self._claims: dict[str, dict[str, Any]] = {}
        # Per-claim last LLM usage for delta-based per-crew recording
        self._last_llm_usage: dict[str, tuple[int, int]] = {}
        # One-shot process-local cost alert state
        self._llm_cost_alert_sent = False

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
            # Reset delta baseline so re-runs start with a clean slate
            self._last_llm_usage[claim_id] = (0, 0)
            logger.debug("Started tracking claim: %s", claim_id)

    def end_claim(self, claim_id: str, status: str = "completed") -> None:
        """Mark the end of claim processing."""
        with self._lock:
            if claim_id in self._claims:
                self._claims[claim_id]["end_time"] = datetime.now(timezone.utc)
                self._claims[claim_id]["status"] = status
            # Clean up baseline to avoid unbounded growth
            self._last_llm_usage.pop(claim_id, None)
            logger.debug("Finished tracking claim: %s with status: %s", claim_id, status)

    def update_claim_type(self, claim_id: str, claim_type: str) -> None:
        """Set claim type for cost attribution (called when router output is known)."""
        with self._lock:
            if claim_id in self._claims:
                self._claims[claim_id]["claim_type"] = claim_type

    def record_crew_usage_delta(
        self,
        claim_id: str,
        current_prompt: int,
        current_completion: int,
        model: str,
        crew: str,
        claim_type: str | None = None,
    ) -> None:
        """Record token delta for a crew (for per-crew cost attribution).

        Call after each crew kickoff. Uses stored last usage to compute delta.
        """
        with self._lock:
            last = self._last_llm_usage.get(claim_id, (0, 0))
            delta_prompt = max(0, current_prompt - last[0])
            delta_completion = max(0, current_completion - last[1])
            self._last_llm_usage[claim_id] = (current_prompt, current_completion)
            if delta_prompt > 0 or delta_completion > 0:
                self.record_llm_call(
                    claim_id=claim_id,
                    model=model,
                    input_tokens=delta_prompt,
                    output_tokens=delta_completion,
                    crew=crew,
                    claim_type=claim_type,
                )

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
        crew: str | None = None,
        claim_type: str | None = None,
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
            crew: Crew name (e.g. router, partial_loss, total_loss)
            claim_type: Claim type for cost attribution
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
            crew=crew,
            claim_type=claim_type,
        )

        # Ensure claim exists and append metric atomically under the metrics lock
        with self._lock:
            if claim_id not in self._claims:
                # Since we're using RLock, we can safely call start_claim from within the lock
                self.start_claim(claim_id)
            self._claims[claim_id]["llm_calls"].append(metric)
            if claim_type:
                self._claims[claim_id]["claim_type"] = claim_type

        record_llm_tokens(input_tokens, output_tokens)

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
                "by_crew": {},
                "by_claim_type": {},
            }

        total_cost = sum(s.total_cost_usd for s in summaries)
        total_tokens = sum(s.total_tokens for s in summaries)
        by_crew = self.get_cost_by_crew()
        by_claim_type = self.get_cost_by_claim_type()

        return {
            "total_claims": len(summaries),
            "total_llm_calls": sum(s.total_llm_calls for s in summaries),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_cost_per_claim": total_cost / len(summaries),
            "avg_tokens_per_claim": total_tokens / len(summaries),
            "avg_latency_per_claim_ms": (
                sum(s.total_latency_ms for s in summaries) / len(summaries)
            ),
            "by_crew": by_crew,
            "by_claim_type": by_claim_type,
        }

    def get_cost_by_crew(self) -> dict[str, dict[str, Any]]:
        """Aggregate cost and tokens by crew name."""
        with self._lock:
            result: dict[str, dict[str, float | int]] = {}
            for claim_data in self._claims.values():
                for m in claim_data.get("llm_calls", []):
                    crew = getattr(m, "crew", None) or "unknown"
                    if crew not in result:
                        result[crew] = {
                            "total_cost_usd": 0.0,
                            "total_tokens": 0,
                            "total_calls": 0,
                        }
                    result[crew]["total_cost_usd"] += m.cost_usd
                    result[crew]["total_tokens"] += m.input_tokens + m.output_tokens
                    result[crew]["total_calls"] += 1
            return result

    def get_cost_by_claim_type(self) -> dict[str, dict[str, Any]]:
        """Aggregate cost and tokens by claim type."""
        with self._lock:
            result: dict[str, dict[str, float | int]] = {}
            for claim_id, claim_data in self._claims.items():
                claim_type = claim_data.get("claim_type") or "unknown"
                if claim_type not in result:
                    result[claim_type] = {
                        "total_cost_usd": 0.0,
                        "total_tokens": 0,
                        "total_claims": 0,
                        "total_calls": 0,
                    }
                for m in claim_data.get("llm_calls", []):
                    result[claim_type]["total_cost_usd"] += m.cost_usd
                    result[claim_type]["total_tokens"] += m.input_tokens + m.output_tokens
                    result[claim_type]["total_calls"] += 1
                result[claim_type]["total_claims"] += 1
            return result

    def get_cost_breakdown(self) -> dict[str, Any]:
        """Full cost breakdown for dashboard: by crew, by claim type, daily totals."""
        summaries = self.get_all_summaries()
        by_crew = self.get_cost_by_crew()
        by_claim_type = self.get_cost_by_claim_type()

        # Daily aggregation (by claim start_time date)
        daily: dict[str, dict[str, float | int]] = {}
        with self._lock:
            for claim_id, claim_data in self._claims.items():
                start = claim_data.get("start_time")
                if start:
                    day = start.strftime("%Y-%m-%d")
                    if day not in daily:
                        daily[day] = {"total_cost_usd": 0.0, "total_tokens": 0, "claims": 0}
                    for m in claim_data.get("llm_calls", []):
                        daily[day]["total_cost_usd"] += m.cost_usd
                        daily[day]["total_tokens"] += m.input_tokens + m.output_tokens
                    daily[day]["claims"] += 1

        total_cost = sum(s.total_cost_usd for s in summaries)
        total_tokens = sum(s.total_tokens for s in summaries)
        self._maybe_send_llm_cost_alert(
            total_cost_usd=total_cost,
            by_crew=by_crew,
            by_claim_type=by_claim_type,
            daily=daily,
        )

        return {
            "global_stats": {
                "total_claims": len(summaries),
                "total_llm_calls": sum(s.total_llm_calls for s in summaries),
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost,
                "avg_cost_per_claim": total_cost / len(summaries) if summaries else 0.0,
                "avg_tokens_per_claim": total_tokens / len(summaries) if summaries else 0.0,
                "avg_latency_per_claim_ms": (
                    sum(s.total_latency_ms for s in summaries) / len(summaries)
                    if summaries
                    else 0.0
                ),
                "by_crew": by_crew,
                "by_claim_type": by_claim_type,
            },
            "by_crew": by_crew,
            "by_claim_type": by_claim_type,
            "daily": daily,
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
        }

    def _maybe_send_llm_cost_alert(
        self,
        *,
        total_cost_usd: float,
        by_crew: dict[str, dict[str, Any]],
        by_claim_type: dict[str, dict[str, Any]],
        daily: dict[str, dict[str, float | int]],
    ) -> None:
        """Best-effort one-time process-local cost threshold alert."""
        config = get_llm_cost_alert_config()
        threshold = config.get("threshold_usd")
        if threshold is None or total_cost_usd <= float(threshold):
            return

        with self._lock:
            if self._llm_cost_alert_sent:
                return
            self._llm_cost_alert_sent = True

        logger.warning(
            "LLM cost alert threshold crossed (process-local): total_cost_usd=%.6f threshold_usd=%.6f",
            total_cost_usd,
            float(threshold),
        )

        webhook_url = config.get("webhook_url")
        if not webhook_url:
            return

        payload: dict[str, Any] = {
            "event": "llm.cost_threshold_crossed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "process_local": True,
            "threshold_usd": float(threshold),
            "total_cost_usd": total_cost_usd,
            "by_crew": by_crew,
            "by_claim_type": by_claim_type,
            "daily": daily,
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to dispatch LLM cost alert webhook to %s: %s", webhook_url, exc)

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


def reset_metrics() -> None:
    """Reset the global ClaimMetrics instance.

    This function is primarily intended for use in tests to avoid
    interference between test cases that rely on the global metrics
    singleton. It clears the existing instance so that the next call
    to get_metrics() creates a fresh ClaimMetrics object.
    """
    global _global_metrics
    with _metrics_lock:
        _global_metrics = None
