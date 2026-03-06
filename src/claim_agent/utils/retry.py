"""Retry utilities with exponential backoff for LLM and I/O operations."""

import logging
from typing import Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Transient errors that are worth retrying (API disconnects, timeouts, etc.)
_base_retryable = (ConnectionError, TimeoutError, OSError)
RETRYABLE_EXCEPTIONS = _base_retryable

# Status codes that indicate transient LLM failures (retry); others (400, 401, 404, etc.) are not retried
_TRANSIENT_STATUS_CODES = {0, 408, 429}  # 0=no response, 408=timeout, 429=rate limit; 5xx checked separately


def _is_transient_litellm_error(exc: BaseException) -> bool:
    """Retry LiteLLM APIError only for transient status codes (0, 408, 429, 5xx)."""
    try:
        from litellm.exceptions import APIError as LiteLLMAPIError
    except ImportError:
        return False
    if not isinstance(exc, LiteLLMAPIError):
        return False
    sc = getattr(exc, "status_code", None)
    if sc is None:
        return False
    try:
        sc = int(sc)
    except (TypeError, ValueError):
        return False
    return sc in _TRANSIENT_STATUS_CODES or 500 <= sc <= 599


def with_llm_retry(
    max_attempts: int = 3,
    min_wait: float = 2.0,
    max_wait: float = 10.0,
    multiplier: float = 1.0,
):
    """Decorator that retries a function with exponential backoff on transient failures.

    Args:
        max_attempts: Maximum number of attempts (default 3).
        min_wait: Minimum wait between retries in seconds (default 2).
        max_wait: Maximum wait between retries in seconds (default 10).
        multiplier: Base multiplier for exponential backoff (default 1).
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(_base_retryable)
            | retry_if_exception(_is_transient_litellm_error),
            reraise=True,
        )
        def wrapper(*args, **kwargs) -> T:
            return func(*args, **kwargs)

        return wrapper

    return decorator
