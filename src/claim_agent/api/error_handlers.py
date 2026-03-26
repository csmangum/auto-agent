"""Global exception handlers that produce structured :class:`ErrorResponse` JSON.

These handlers are registered on the FastAPI application in ``server.py``.
They ensure every error response — whether from a domain exception or from
FastAPI's own validation machinery — follows the same schema::

    {
      "error_code": "<MACHINE_READABLE_CODE>",
      "detail":     "<human-readable message>",
      "details":    { ... }   // optional, present for rich domain exceptions
    }

The ``detail`` key is intentionally kept so that existing clients that read
``response.json()["detail"]`` continue to work without modification.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from claim_agent.exceptions import (
    AdapterError,
    ClaimAgentError,
    ClaimAlreadyProcessingError,
    ClaimNotFoundError,
    ClaimWorkflowTimeoutError,
    DomainValidationError,
    EscalationError,
    InvalidClaimTransitionError,
    PaymentAuthorityError,
    PaymentNotFoundError,
    ReserveAuthorityError,
    TokenBudgetExceeded,
)
from claim_agent.models.error import ErrorResponse

# ---------------------------------------------------------------------------
# Mapping: HTTP status code → generic error_code
# ---------------------------------------------------------------------------

_STATUS_TO_CODE: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    410: "GONE",
    411: "LENGTH_REQUIRED",
    413: "REQUEST_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


def _error_code_for_status(status_code: int) -> str:
    return _STATUS_TO_CODE.get(status_code, "ERROR")


def _json(
    status_code: int,
    error_code: str,
    detail: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error_code=error_code, detail=detail, details=details)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Override FastAPI / Starlette default handlers
# ---------------------------------------------------------------------------


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Override the default HTTPException handler to include ``error_code``."""
    assert isinstance(exc, HTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    error_code = _error_code_for_status(exc.status_code)
    headers = dict(exc.headers) if exc.headers else None
    return _json(exc.status_code, error_code, detail, headers=headers)


async def request_validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Override the default RequestValidationError handler to include ``error_code``."""
    assert isinstance(exc, RequestValidationError)
    # exc.errors() may contain non-JSON-serializable objects (e.g. ValueError);
    # convert each error to a plain dict with only string-safe values.
    raw_errors = exc.errors()
    safe_errors = [
        {
            "loc": [str(loc) for loc in e.get("loc", [])],
            "msg": str(e.get("msg", "")),
            "type": str(e.get("type", "")),
        }
        for e in raw_errors
    ]
    detail = "; ".join(
        f"{' -> '.join(str(loc) for loc in e.get('loc', []))}: {e.get('msg', '')}"
        for e in raw_errors
    ) or "Request validation failed"
    return _json(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "VALIDATION_ERROR",
        detail,
        details={"errors": safe_errors},
    )


# ---------------------------------------------------------------------------
# Domain exception handlers
# ---------------------------------------------------------------------------


async def claim_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json(status.HTTP_404_NOT_FOUND, "CLAIM_NOT_FOUND", str(exc))


async def payment_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json(status.HTTP_404_NOT_FOUND, "PAYMENT_NOT_FOUND", str(exc))


async def domain_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json(status.HTTP_400_BAD_REQUEST, "DOMAIN_VALIDATION_ERROR", str(exc))


async def invalid_claim_transition_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, InvalidClaimTransitionError)
    return _json(
        status.HTTP_409_CONFLICT,
        "INVALID_CLAIM_TRANSITION",
        str(exc),
        details={
            "claim_id": exc.claim_id,
            "from_status": exc.from_status,
            "to_status": exc.to_status,
            "reason": exc.reason,
        },
    )


async def claim_already_processing_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClaimAlreadyProcessingError)
    return _json(
        status.HTTP_409_CONFLICT,
        "CLAIM_ALREADY_PROCESSING",
        str(exc),
        details={"claim_id": exc.claim_id},
    )


async def reserve_authority_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ReserveAuthorityError)
    return _json(
        status.HTTP_403_FORBIDDEN,
        "RESERVE_AUTHORITY_EXCEEDED",
        str(exc),
        details={
            "amount": exc.amount,
            "limit": exc.limit,
            "actor_id": exc.actor_id,
            "role": exc.role,
        },
    )


async def payment_authority_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PaymentAuthorityError)
    return _json(
        status.HTTP_403_FORBIDDEN,
        "PAYMENT_AUTHORITY_EXCEEDED",
        str(exc),
        details={
            "amount": exc.amount,
            "limit": exc.limit,
            "actor_id": exc.actor_id,
            "role": exc.role,
        },
    )


async def token_budget_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, TokenBudgetExceeded)
    return _json(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "TOKEN_BUDGET_EXCEEDED",
        str(exc),
        details={
            "claim_id": exc.claim_id,
            "total_tokens": exc.total_tokens,
            "total_calls": exc.total_calls,
        },
    )


async def claim_workflow_timeout_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ClaimWorkflowTimeoutError)
    return _json(
        status.HTTP_504_GATEWAY_TIMEOUT,
        "WORKFLOW_TIMEOUT",
        str(exc),
        details={
            "claim_id": exc.claim_id,
            "elapsed_seconds": exc.elapsed_seconds,
            "timeout_seconds": exc.timeout_seconds,
        },
    )


async def adapter_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json(status.HTTP_502_BAD_GATEWAY, "ADAPTER_ERROR", str(exc))


async def escalation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return _json(status.HTTP_500_INTERNAL_SERVER_ERROR, "ESCALATION_ERROR", str(exc))


async def claim_agent_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for any unhandled :class:`ClaimAgentError` subclass."""
    return _json(status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", str(exc))


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_exception_handlers(app: Any) -> None:  # noqa: ANN401
    """Register all structured error handlers on *app*.

    Call this inside :func:`create_app` **after** middleware is added so that
    domain exceptions propagate through middleware unchanged and are caught here.
    Ordering matters: more-specific subclasses must be registered before their
    base classes (FastAPI / Starlette searches handlers in registration order
    for exact type matches, but we add them by type so each is exact).
    """
    # Override default FastAPI handlers
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)

    # Domain exceptions — specific subclasses before base classes
    app.add_exception_handler(ClaimNotFoundError, claim_not_found_handler)
    app.add_exception_handler(PaymentNotFoundError, payment_not_found_handler)
    app.add_exception_handler(DomainValidationError, domain_validation_handler)
    app.add_exception_handler(InvalidClaimTransitionError, invalid_claim_transition_handler)
    app.add_exception_handler(ClaimAlreadyProcessingError, claim_already_processing_handler)
    app.add_exception_handler(ReserveAuthorityError, reserve_authority_handler)
    app.add_exception_handler(PaymentAuthorityError, payment_authority_handler)
    app.add_exception_handler(TokenBudgetExceeded, token_budget_exceeded_handler)
    app.add_exception_handler(ClaimWorkflowTimeoutError, claim_workflow_timeout_handler)
    app.add_exception_handler(AdapterError, adapter_error_handler)
    app.add_exception_handler(EscalationError, escalation_error_handler)
    # Base class last — catches any ClaimAgentError not matched above
    app.add_exception_handler(ClaimAgentError, claim_agent_error_handler)
