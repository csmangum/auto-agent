"""Standard error response model for all API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Structured error response returned by all API error handlers.

    Attributes:
        error_code: Machine-readable identifier for the error type
                    (e.g. ``"CLAIM_NOT_FOUND"``, ``"VALIDATION_ERROR"``).
        detail:     Human-readable error message for most errors, or a list
                    of validation error dicts for 422 responses (mirrors
                    FastAPI's defaults so existing clients keep working).
        details:    Optional dict of structured context specific to the error
                    (e.g. ``claim_id``, ``from_status``, ``to_status``).
    """

    error_code: str
    detail: str | list[dict[str, Any]]
    details: dict[str, Any] | None = None
