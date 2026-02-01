"""LangSmith and LiteLLM tracing integration for LLM call observability.

This module provides:
- LangSmith integration for LLM call tracing
- LiteLLM callback for token/cost tracking
- Automatic trace context propagation with claim IDs
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class TracingConfig:
    """Configuration for tracing backends."""

    # LangSmith settings
    langsmith_enabled: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "claim-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # General tracing settings
    trace_llm_calls: bool = True
    trace_tool_calls: bool = True
    log_prompts: bool = False  # Set to True to log full prompts (may contain PII)
    log_responses: bool = False  # Set to True to log full responses

    @classmethod
    def from_env(cls) -> "TracingConfig":
        """Create config from environment variables."""
        return cls(
            langsmith_enabled=os.environ.get("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes"),
            langsmith_api_key=os.environ.get("LANGSMITH_API_KEY", ""),
            langsmith_project=os.environ.get("LANGSMITH_PROJECT", "claim-agent"),
            langsmith_endpoint=os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
            trace_llm_calls=os.environ.get("CLAIM_AGENT_TRACE_LLM", "true").lower() in ("true", "1", "yes"),
            trace_tool_calls=os.environ.get("CLAIM_AGENT_TRACE_TOOLS", "true").lower() in ("true", "1", "yes"),
            log_prompts=os.environ.get("CLAIM_AGENT_LOG_PROMPTS", "false").lower() in ("true", "1", "yes"),
            log_responses=os.environ.get("CLAIM_AGENT_LOG_RESPONSES", "false").lower() in ("true", "1", "yes"),
        )


@dataclass
class LLMCallTrace:
    """Represents a single LLM call trace."""

    trace_id: str
    claim_id: str | None
    model: str
    start_time: datetime
    end_time: datetime | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    status: str = "pending"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def complete(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        error: str | None = None,
    ) -> None:
        """Mark the trace as complete."""
        self.end_time = datetime.now(timezone.utc)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens
        self.cost_usd = cost_usd
        self.latency_ms = (self.end_time - self.start_time).total_seconds() * 1000
        self.status = "error" if error else "success"
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "trace_id": self.trace_id,
            "claim_id": self.claim_id,
            "model": self.model,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }


class TracingCallback:
    """Custom callback for LLM call tracing compatible with LiteLLM.

    This callback can be used with LiteLLM's callback system to track:
    - Token usage per call
    - Cost per call
    - Latency
    - Errors

    Usage:
        from claim_agent.observability import TracingCallback

        callback = TracingCallback(claim_id="CLM-123")
        # Use with LiteLLM or pass to CrewAI
    """

    def __init__(
        self,
        claim_id: str | None = None,
        config: TracingConfig | None = None,
        metrics_collector: Any | None = None,
    ):
        self.claim_id = claim_id
        self.config = config or TracingConfig.from_env()
        self.metrics_collector = metrics_collector
        self._traces: dict[str, LLMCallTrace] = {}
        self._trace_counter = 0
        self._logger = logging.getLogger(__name__)

    def set_claim_id(self, claim_id: str) -> None:
        """Set the claim ID for tracing context."""
        self.claim_id = claim_id

    def _generate_trace_id(self) -> str:
        """Generate a unique trace ID."""
        self._trace_counter += 1
        timestamp = int(time.time() * 1000)
        return f"trace-{timestamp}-{self._trace_counter}"

    def log_pre_api_call(
        self,
        model: str,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Log before an LLM API call. Returns trace_id."""
        trace_id = self._generate_trace_id()

        trace = LLMCallTrace(
            trace_id=trace_id,
            claim_id=self.claim_id,
            model=model,
            start_time=datetime.now(timezone.utc),
            metadata={
                "agent": kwargs.get("agent"),
                "task": kwargs.get("task"),
            },
        )
        self._traces[trace_id] = trace

        if self.config.trace_llm_calls:
            self._logger.info(
                "[llm_call_start] trace_id=%s, claim_id=%s, model=%s",
                trace_id,
                self.claim_id,
                model,
            )

        return trace_id

    def log_post_api_call(
        self,
        trace_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        response: Any = None,
        error: str | None = None,
    ) -> LLMCallTrace | None:
        """Log after an LLM API call completes."""
        trace = self._traces.get(trace_id)
        if not trace:
            return None

        trace.complete(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            error=error,
        )

        if self.config.trace_llm_calls:
            self._logger.info(
                "[llm_call_complete] trace_id=%s, claim_id=%s, tokens=%d, cost=$%.4f, latency=%.0fms, status=%s",
                trace_id,
                self.claim_id,
                trace.total_tokens,
                cost_usd,
                trace.latency_ms,
                trace.status,
            )

        # Record metrics
        if self.metrics_collector:
            self.metrics_collector.record_llm_call(
                claim_id=self.claim_id or "unknown",
                model=trace.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                latency_ms=trace.latency_ms,
                status=trace.status,
                error=error,
            )

        return trace

    def get_traces(self) -> list[LLMCallTrace]:
        """Get all traces for this callback instance."""
        return list(self._traces.values())

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics for all traces."""
        traces = self.get_traces()
        if not traces:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "avg_latency_ms": 0.0,
            }

        completed = [t for t in traces if t.status in ("success", "error")]
        return {
            "total_calls": len(traces),
            "successful_calls": len([t for t in completed if t.status == "success"]),
            "failed_calls": len([t for t in completed if t.status == "error"]),
            "total_tokens": sum(t.total_tokens for t in completed),
            "total_input_tokens": sum(t.input_tokens for t in completed),
            "total_output_tokens": sum(t.output_tokens for t in completed),
            "total_cost_usd": sum(t.cost_usd for t in completed),
            "avg_latency_ms": (
                sum(t.latency_ms for t in completed) / len(completed) if completed else 0.0
            ),
            "total_latency_ms": sum(t.latency_ms for t in completed),
        }


def setup_langsmith() -> bool:
    """Set up LangSmith tracing environment variables.

    Returns True if LangSmith was successfully configured.
    """
    config = TracingConfig.from_env()

    if not config.langsmith_enabled:
        logger.debug("LangSmith tracing is disabled")
        return False

    if not config.langsmith_api_key:
        logger.warning("LANGSMITH_API_KEY not set, LangSmith tracing disabled")
        return False

    # Set environment variables for LangSmith/LangChain integration
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = config.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = config.langsmith_project
    os.environ["LANGCHAIN_ENDPOINT"] = config.langsmith_endpoint

    logger.info(
        "LangSmith tracing enabled for project: %s", config.langsmith_project
    )
    return True


def get_tracing_callback(
    claim_id: str | None = None,
    metrics_collector: Any | None = None,
) -> TracingCallback:
    """Get a TracingCallback instance.

    Args:
        claim_id: Optional claim ID for context
        metrics_collector: Optional ClaimMetrics instance for recording metrics

    Returns:
        TracingCallback instance
    """
    config = TracingConfig.from_env()
    return TracingCallback(
        claim_id=claim_id,
        config=config,
        metrics_collector=metrics_collector,
    )


# LiteLLM callback functions for direct integration
# These can be used with litellm.callbacks
class LiteLLMTracingCallback:
    """LiteLLM-compatible callback class for tracing.

    Usage with LiteLLM:
        import litellm
        from claim_agent.observability import LiteLLMTracingCallback

        callback = LiteLLMTracingCallback(claim_id="CLM-123")
        litellm.callbacks = [callback]
    """

    def __init__(self, claim_id: str | None = None, metrics_collector: Any | None = None):
        self.claim_id = claim_id
        self.metrics_collector = metrics_collector
        self._pending_calls: dict[str, dict[str, Any]] = {}
        self._logger = logging.getLogger(__name__)

    def set_claim_id(self, claim_id: str) -> None:
        """Set the claim ID for tracing context."""
        self.claim_id = claim_id

    def log_pre_api_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> None:
        """Called before the LLM API call."""
        call_id = kwargs.get("litellm_call_id", str(time.time()))
        self._pending_calls[call_id] = {
            "model": model,
            "start_time": time.time(),
            "claim_id": self.claim_id,
        }
        self._logger.info(
            "[litellm_call_start] call_id=%s, claim_id=%s, model=%s",
            call_id,
            self.claim_id,
            model,
        )

    def log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: float,
        end_time: float,
    ) -> None:
        """Called after successful LLM API call."""
        call_id = kwargs.get("litellm_call_id", "")
        call_info = self._pending_calls.pop(call_id, {})

        # Extract usage info from response
        usage = getattr(response_obj, "usage", None) or {}
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        elif hasattr(usage, "__dict__"):
            usage = usage.__dict__

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

        # Calculate cost if available
        cost = getattr(response_obj, "_hidden_params", {}).get("response_cost", 0.0)
        latency_ms = (end_time - start_time) * 1000

        self._logger.info(
            "[litellm_call_success] call_id=%s, claim_id=%s, model=%s, "
            "tokens=%d, cost=$%.4f, latency=%.0fms",
            call_id,
            call_info.get("claim_id", self.claim_id),
            call_info.get("model", kwargs.get("model", "unknown")),
            total_tokens,
            cost,
            latency_ms,
        )

        # Record metrics
        if self.metrics_collector:
            self.metrics_collector.record_llm_call(
                claim_id=call_info.get("claim_id") or self.claim_id or "unknown",
                model=call_info.get("model", kwargs.get("model", "unknown")),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                status="success",
            )

    def log_failure_event(
        self,
        kwargs: dict[str, Any],
        exception: Exception,
        start_time: float,
        end_time: float,
    ) -> None:
        """Called after failed LLM API call."""
        call_id = kwargs.get("litellm_call_id", "")
        call_info = self._pending_calls.pop(call_id, {})

        latency_ms = (end_time - start_time) * 1000

        self._logger.error(
            "[litellm_call_failure] call_id=%s, claim_id=%s, model=%s, "
            "error=%s, latency=%.0fms",
            call_id,
            call_info.get("claim_id", self.claim_id),
            call_info.get("model", kwargs.get("model", "unknown")),
            str(exception),
            latency_ms,
        )

        # Record metrics
        if self.metrics_collector:
            self.metrics_collector.record_llm_call(
                claim_id=call_info.get("claim_id") or self.claim_id or "unknown",
                model=call_info.get("model", kwargs.get("model", "unknown")),
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
                status="error",
                error=str(exception),
            )
