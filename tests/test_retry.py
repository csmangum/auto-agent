"""Tests for retry utility."""

import pytest

from claim_agent.utils.retry import RETRYABLE_EXCEPTIONS, with_llm_retry


def test_retryable_exceptions_include_connection_and_timeout():
    """Transient errors that should be retried are in RETRYABLE_EXCEPTIONS."""
    assert ConnectionError in RETRYABLE_EXCEPTIONS
    assert TimeoutError in RETRYABLE_EXCEPTIONS
    assert OSError in RETRYABLE_EXCEPTIONS


def test_with_llm_retry_succeeds_first_time():
    """Decorated function that succeeds on first call returns result."""
    @with_llm_retry(max_attempts=3)
    def ok():
        return 42
    assert ok() == 42


def test_with_llm_retry_reraises_non_retryable():
    """Non-retryable exception is reraised immediately."""
    @with_llm_retry(max_attempts=3)
    def fail():
        raise ValueError("not retryable")
    with pytest.raises(ValueError, match="not retryable"):
        fail()


def test_with_llm_retry_retries_on_connection_error():
    """Retries on ConnectionError then succeeds."""
    attempts = []

    @with_llm_retry(max_attempts=3, min_wait=0.01, max_wait=0.05)
    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise ConnectionError("transient")
        return "ok"

    assert flaky() == "ok"
    assert len(attempts) == 2


def test_with_llm_retry_retries_on_litellm_api_error():
    """Retries on litellm APIError (e.g. server disconnect) then succeeds."""
    pytest.importorskip("litellm")
    from litellm.exceptions import APIError

    attempts = []

    @with_llm_retry(max_attempts=3, min_wait=0.01, max_wait=0.05)
    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise APIError(
                status_code=0,
                message="Server disconnected without sending a response",
                llm_provider="openrouter",
                model="test",
            )
        return "ok"

    assert flaky() == "ok"
    assert len(attempts) == 2


def test_with_llm_retry_does_not_retry_on_non_transient_litellm_error():
    """Does not retry on LiteLLM APIError with non-transient status (e.g. 400, 401)."""
    pytest.importorskip("litellm")
    from litellm.exceptions import APIError

    attempts = []

    @with_llm_retry(max_attempts=3, min_wait=0.01, max_wait=0.05)
    def bad_request():
        attempts.append(1)
        raise APIError(
            status_code=400,
            message="Bad request",
            llm_provider="openai",
            model="test",
        )

    with pytest.raises(APIError):
        bad_request()
    assert len(attempts) == 1
