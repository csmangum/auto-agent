"""Structured logging with claim ID context for observability.

This module provides:
- ClaimLogger: A structured logger that attaches claim_id to all log messages
- claim_context: A context manager for setting claim context
- log_claim_event: Helper for logging claim-specific events
"""

import json
import logging
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

# Thread-local storage for claim context
_context = threading.local()


def _get_claim_context() -> dict[str, Any]:
    """Get the current claim context from thread-local storage."""
    return getattr(_context, "claim_data", {})


def _set_claim_context(data: dict[str, Any]) -> None:
    """Set the claim context in thread-local storage."""
    _context.claim_data = data


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, include_timestamp: bool = True):
        super().__init__()
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON with claim context."""
        log_data: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if self.include_timestamp:
            log_data["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Add claim context if available
        claim_ctx = _get_claim_context()
        if claim_ctx:
            log_data["claim_id"] = claim_ctx.get("claim_id")
            log_data["claim_type"] = claim_ctx.get("claim_type")
            log_data["policy_number"] = claim_ctx.get("policy_number")

        # Add extra fields from the record
        if hasattr(record, "claim_id") and record.claim_id:
            log_data["claim_id"] = record.claim_id
        if hasattr(record, "claim_type") and record.claim_type:
            log_data["claim_type"] = record.claim_type
        if hasattr(record, "extra_data") and record.extra_data:
            log_data["data"] = record.extra_data

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add source location for debugging
        log_data["source"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }

        return json.dumps(log_data)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter with claim context prefix."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with claim context prefix."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        
        # Build context prefix
        ctx_parts = []
        claim_ctx = _get_claim_context()
        
        claim_id = getattr(record, "claim_id", None) or claim_ctx.get("claim_id")
        if claim_id:
            ctx_parts.append(f"claim={claim_id}")
        
        claim_type = getattr(record, "claim_type", None) or claim_ctx.get("claim_type")
        if claim_type:
            ctx_parts.append(f"type={claim_type}")

        ctx_str = f" [{', '.join(ctx_parts)}]" if ctx_parts else ""
        
        # Format message
        message = record.getMessage()
        
        # Add extra data if present
        if hasattr(record, "extra_data") and record.extra_data:
            message += f" | {record.extra_data}"

        return f"{timestamp} {record.levelname:8}{ctx_str} {record.name}: {message}"


class ClaimLogger(logging.LoggerAdapter):
    """Logger adapter that adds claim context to all log messages."""

    def __init__(self, logger: logging.Logger, claim_id: str | None = None):
        super().__init__(logger, {})
        self._claim_id = claim_id
        self._claim_type: str | None = None
        self._extra_context: dict[str, Any] = {}

    def set_claim_id(self, claim_id: str) -> None:
        """Set the claim ID for this logger."""
        self._claim_id = claim_id

    def set_claim_type(self, claim_type: str) -> None:
        """Set the claim type for this logger."""
        self._claim_type = claim_type

    def set_context(self, **kwargs: Any) -> None:
        """Set additional context fields."""
        self._extra_context.update(kwargs)

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Add claim context to log kwargs."""
        extra = kwargs.get("extra", {})
        
        if self._claim_id:
            extra["claim_id"] = self._claim_id
        if self._claim_type:
            extra["claim_type"] = self._claim_type
        if self._extra_context:
            extra["extra_data"] = self._extra_context
            
        kwargs["extra"] = extra
        return msg, kwargs

    def log_event(
        self,
        event: str,
        level: int = logging.INFO,
        **data: Any,
    ) -> None:
        """Log a structured event with additional data."""
        message = f"[{event}]"
        if data:
            details = ", ".join(f"{k}={v}" for k, v in data.items())
            message = f"{message} {details}"
        
        extra = {
            "claim_id": self._claim_id,
            "claim_type": self._claim_type,
            "extra_data": {"event": event, **data},
        }
        self.log(level, message, extra=extra)


def get_logger(
    name: str,
    claim_id: str | None = None,
    structured: bool | None = None,
) -> ClaimLogger:
    """Get a ClaimLogger instance.

    Args:
        name: Logger name (typically __name__)
        claim_id: Optional claim ID to attach to all logs
        structured: If True, use JSON format. If False, use human-readable.
                   If None, use CLAIM_AGENT_LOG_FORMAT env var (default: human)

    Returns:
        ClaimLogger instance
    """
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        if structured is None:
            log_format = os.environ.get("CLAIM_AGENT_LOG_FORMAT", "human").lower()
            structured = log_format == "json"
        
        handler = logging.StreamHandler(sys.stdout)
        if structured:
            handler.setFormatter(StructuredFormatter())
        else:
            handler.setFormatter(HumanReadableFormatter())
        
        logger.addHandler(handler)
        
        # Set log level from environment
        log_level = os.environ.get("CLAIM_AGENT_LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Prevent duplicate logs from propagating to parent handlers
        logger.propagate = False
    
    return ClaimLogger(logger, claim_id)


@contextmanager
def claim_context(
    claim_id: str,
    claim_type: str | None = None,
    policy_number: str | None = None,
    **extra: Any,
):
    """Context manager for setting claim context on all logs within the block.

    Usage:
        with claim_context(claim_id="CLM-123", claim_type="new"):
            logger.info("Processing claim")  # Will include claim_id in output
    """
    old_context = _get_claim_context()
    new_context = {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "policy_number": policy_number,
        **extra,
    }
    _set_claim_context(new_context)
    try:
        yield
    finally:
        _set_claim_context(old_context)


def log_claim_event(
    logger: logging.Logger | ClaimLogger,
    event: str,
    claim_id: str | None = None,
    level: int = logging.INFO,
    **data: Any,
) -> None:
    """Log a claim event with structured data.

    Args:
        logger: Logger instance
        event: Event name (e.g., "claim_created", "workflow_started")
        claim_id: Claim ID (optional if using claim_context)
        level: Log level
        **data: Additional event data
    """
    message = f"[{event}]"
    if data:
        details = ", ".join(f"{k}={v}" for k, v in data.items())
        message = f"{message} {details}"
    
    extra = {"claim_id": claim_id, "extra_data": {"event": event, **data}}
    logger.log(level, message, extra=extra)
