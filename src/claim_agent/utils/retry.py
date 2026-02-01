"""Retry utilities with exponential backoff for LLM and I/O operations."""

import logging
from typing import Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Transient errors that are worth retrying
RETRYABLE_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


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
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
        )
        def wrapper(*args, **kwargs) -> T:
            return func(*args, **kwargs)

        return wrapper

    return decorator
