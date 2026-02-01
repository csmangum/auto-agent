"""Observability and tracing module for production-readiness.

This module provides:
- Structured logging with claim ID context
- LangSmith/LiteLLM tracing for LLM calls
- Cost and latency tracking per claim
"""

from claim_agent.observability.logger import (
    ClaimLogger,
    get_logger,
    claim_context,
    log_claim_event,
)
from claim_agent.observability.tracing import (
    TracingConfig,
    get_tracing_callback,
    setup_langsmith,
    TracingCallback,
)
from claim_agent.observability.metrics import (
    ClaimMetrics,
    get_metrics,
    track_llm_call,
    get_claim_summary,
)

__all__ = [
    # Logger
    "ClaimLogger",
    "get_logger",
    "claim_context",
    "log_claim_event",
    # Tracing
    "TracingConfig",
    "get_tracing_callback",
    "setup_langsmith",
    "TracingCallback",
    # Metrics
    "ClaimMetrics",
    "get_metrics",
    "track_llm_call",
    "get_claim_summary",
]
