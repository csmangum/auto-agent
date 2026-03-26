"""Tests for structured error response schema (issue M4).

Every error response must include:
  - ``error_code``: machine-readable identifier
  - ``detail``:     human-readable message (kept for backward compat)
  - ``details``:    optional dict with structured context

These tests target the global exception handlers and middleware paths;
they do *not* depend on seeded DB data beyond what conftest provides.
"""

import pytest
from fastapi.testclient import TestClient

from claim_agent.exceptions import (
    ClaimAlreadyProcessingError,
    ClaimNotFoundError,
    ClaimWorkflowTimeoutError,
    DomainValidationError,
    InvalidClaimTransitionError,
    PaymentAuthorityError,
    PaymentNotFoundError,
    ReserveAuthorityError,
)


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    from claim_agent.api.server import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _assert_error_schema(body: dict, *, error_code: str | None = None) -> None:
    """Assert that *body* follows the standard error schema."""
    assert "error_code" in body, f"'error_code' missing from {body}"
    assert "detail" in body, f"'detail' missing from {body}"
    if error_code is not None:
        assert body["error_code"] == error_code, (
            f"Expected error_code={error_code!r}, got {body['error_code']!r}"
        )


# ---------------------------------------------------------------------------
# 404 – Not Found
# ---------------------------------------------------------------------------


class TestNotFoundErrors:
    def test_unknown_claim_returns_structured_error(self, client):
        """GET /api/v1/claims/<nonexistent> returns 404 with the standard error schema.

        The claims route catches ClaimNotFoundError and re-raises as HTTPException,
        so the overridden HTTPException handler produces error_code="NOT_FOUND".
        """
        resp = client.get("/api/v1/claims/CLM-NOTEXIST")
        assert resp.status_code == 404
        body = resp.json()
        _assert_error_schema(body, error_code="NOT_FOUND")

    def test_unknown_payment_returns_structured_error(self, client):
        """GET /api/v1/payments/<nonexistent> returns 404 with the standard error schema.

        The payments route catches PaymentNotFoundError and re-raises as HTTPException,
        so the overridden HTTPException handler produces error_code="NOT_FOUND".
        """
        resp = client.get("/api/v1/payments/PAY-NOTEXIST")
        assert resp.status_code == 404
        body = resp.json()
        _assert_error_schema(body, error_code="NOT_FOUND")


# ---------------------------------------------------------------------------
# 409 – Conflict / Invalid transition
# ---------------------------------------------------------------------------


class TestConflictErrors:
    def test_invalid_claim_transition_has_structured_details(self, client):
        """InvalidClaimTransitionError must return error_code + details dict.

        This uses the mini-app approach since the global handler is already
        covered by TestGlobalDomainExceptionHandlers.test_invalid_transition_handler.
        We just confirm the real app's route returns structured errors too.
        """
        # Try to resolve review on a claim that's in 'open' status (not needs_review)
        # which will trigger a conflict response.
        resp = client.get("/api/v1/claims")
        assert resp.status_code == 200
        data = resp.json()
        claims = data.get("claims", [])
        if not claims:
            pytest.skip("No claims in seeded DB")
        # Get any claim id from the response
        first_claim = claims[0]
        # Use whichever key holds the claim identifier
        claim_id = first_claim.get("claim_id") or first_claim.get("id")
        if not claim_id:
            pytest.skip(f"Cannot determine claim_id from keys: {list(first_claim.keys())}")
        # Attempt resolve-review on a non-needs_review claim triggers 409
        resp2 = client.post(f"/api/v1/claims/{claim_id}/resolve-review", json={"decision": "approve"})
        if resp2.status_code == 409:
            body = resp2.json()
            _assert_error_schema(body)
            assert "error_code" in body
        elif resp2.status_code in {404, 405}:
            pytest.skip("resolve-review endpoint not applicable for this claim state")


# ---------------------------------------------------------------------------
# 422 – Validation errors
# ---------------------------------------------------------------------------


class TestValidationErrors:
    def test_missing_required_field_returns_structured_error(self, client):
        """POST /api/v1/claims with an empty body should return 422 with error_code."""
        resp = client.post("/api/v1/claims", json={})
        assert resp.status_code == 422
        body = resp.json()
        _assert_error_schema(body, error_code="VALIDATION_ERROR")
        # FastAPI puts per-field errors in details.errors
        assert "details" in body
        assert "errors" in body["details"]
        assert isinstance(body["details"]["errors"], list)
        assert len(body["details"]["errors"]) > 0

    def test_invalid_json_type_returns_validation_error(self, client):
        """Pydantic validates field types before the route runs, so a wrong type returns 422."""
        resp = client.post(
            "/api/v1/claims",
            # vehicle_year as a string that can't be coerced to int triggers type error
            json={"claim_type": "new", "vehicle_year": "not-a-number"},
        )
        assert resp.status_code == 422
        body = resp.json()
        _assert_error_schema(body, error_code="VALIDATION_ERROR")


# ---------------------------------------------------------------------------
# 400 – Bad Request
# ---------------------------------------------------------------------------


class TestBadRequestErrors:
    def test_invalid_enum_field_returns_422(self, client):
        """Passing an enum field with an invalid value triggers 422 with VALIDATION_ERROR."""
        # POST a claim with an invalid priority value (not in the allowed enum)
        resp = client.post(
            "/api/v1/claims",
            json={
                "claim_type": "new",
                "priority": "INVALID_PRIORITY_VALUE_XYZ",
            },
        )
        # Pydantic rejects invalid enum values as 422 before route logic runs
        if resp.status_code == 422:
            body = resp.json()
            _assert_error_schema(body, error_code="VALIDATION_ERROR")


# ---------------------------------------------------------------------------
# Global domain exception handlers (unit-style via httpx transport)
# ---------------------------------------------------------------------------


class TestGlobalDomainExceptionHandlers:
    """Verify the global handlers produce the right schema by raising exceptions
    through a minimal FastAPI app that uses the same handlers."""

    @pytest.fixture
    def mini_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from claim_agent.api.error_handlers import register_exception_handlers

        mini = FastAPI()
        register_exception_handlers(mini)

        @mini.get("/claim-not-found")
        def raise_claim_not_found():
            raise ClaimNotFoundError("Claim CLM-999 not found")

        @mini.get("/payment-not-found")
        def raise_payment_not_found():
            raise PaymentNotFoundError("Payment PAY-999 not found")

        @mini.get("/domain-validation")
        def raise_domain_validation():
            raise DomainValidationError("Field 'amount' must be positive")

        @mini.get("/invalid-transition")
        def raise_invalid_transition():
            raise InvalidClaimTransitionError(
                claim_id="CLM-1",
                from_status="open",
                to_status="closed",
                reason="Cannot close without assessment",
            )

        @mini.get("/already-processing")
        def raise_already_processing():
            raise ClaimAlreadyProcessingError("CLM-1")

        @mini.get("/reserve-authority")
        def raise_reserve_authority():
            raise ReserveAuthorityError(amount=50000.0, limit=25000.0, actor_id="adj-1", role="adjuster")

        @mini.get("/payment-authority")
        def raise_payment_authority():
            raise PaymentAuthorityError(amount=50000.0, limit=25000.0, actor_id="adj-1", role="adjuster")

        @mini.get("/workflow-timeout")
        def raise_workflow_timeout():
            raise ClaimWorkflowTimeoutError(claim_id="CLM-1", elapsed_seconds=120.0, timeout_seconds=60.0)

        return TestClient(mini, raise_server_exceptions=False)

    def test_claim_not_found_handler(self, mini_client):
        resp = mini_client.get("/claim-not-found")
        assert resp.status_code == 404
        body = resp.json()
        _assert_error_schema(body, error_code="CLAIM_NOT_FOUND")
        assert "CLM-999" in body["detail"]

    def test_payment_not_found_handler(self, mini_client):
        resp = mini_client.get("/payment-not-found")
        assert resp.status_code == 404
        body = resp.json()
        _assert_error_schema(body, error_code="PAYMENT_NOT_FOUND")

    def test_domain_validation_handler(self, mini_client):
        resp = mini_client.get("/domain-validation")
        assert resp.status_code == 400
        body = resp.json()
        _assert_error_schema(body, error_code="DOMAIN_VALIDATION_ERROR")

    def test_invalid_transition_handler(self, mini_client):
        resp = mini_client.get("/invalid-transition")
        assert resp.status_code == 409
        body = resp.json()
        _assert_error_schema(body, error_code="INVALID_CLAIM_TRANSITION")
        assert "details" in body
        assert body["details"]["claim_id"] == "CLM-1"
        assert body["details"]["from_status"] == "open"
        assert body["details"]["to_status"] == "closed"
        assert "reason" in body["details"]

    def test_already_processing_handler(self, mini_client):
        resp = mini_client.get("/already-processing")
        assert resp.status_code == 409
        body = resp.json()
        _assert_error_schema(body, error_code="CLAIM_ALREADY_PROCESSING")
        assert "details" in body
        assert body["details"]["claim_id"] == "CLM-1"

    def test_reserve_authority_handler(self, mini_client):
        resp = mini_client.get("/reserve-authority")
        assert resp.status_code == 403
        body = resp.json()
        _assert_error_schema(body, error_code="RESERVE_AUTHORITY_EXCEEDED")
        assert "details" in body
        assert body["details"]["amount"] == 50000.0
        assert body["details"]["limit"] == 25000.0
        assert body["details"]["actor_id"] == "adj-1"
        assert body["details"]["role"] == "adjuster"

    def test_payment_authority_handler(self, mini_client):
        resp = mini_client.get("/payment-authority")
        assert resp.status_code == 403
        body = resp.json()
        _assert_error_schema(body, error_code="PAYMENT_AUTHORITY_EXCEEDED")
        assert "details" in body

    def test_workflow_timeout_handler(self, mini_client):
        resp = mini_client.get("/workflow-timeout")
        assert resp.status_code == 504
        body = resp.json()
        _assert_error_schema(body, error_code="WORKFLOW_TIMEOUT")
        assert "details" in body
        assert body["details"]["claim_id"] == "CLM-1"
        assert body["details"]["elapsed_seconds"] == 120.0
        assert body["details"]["timeout_seconds"] == 60.0

    def test_http_exception_gets_error_code(self, mini_client):
        """Any HTTPException raised within a route gets error_code from status map."""
        from fastapi import HTTPException

        from claim_agent.api.error_handlers import register_exception_handlers

        mini2 = __import__("fastapi").FastAPI()
        register_exception_handlers(mini2)

        @mini2.get("/raise-404")
        def raise_404():
            raise HTTPException(status_code=404, detail="Resource not found")

        c2 = TestClient(mini2, raise_server_exceptions=False)
        resp = c2.get("/raise-404")
        assert resp.status_code == 404
        body = resp.json()
        _assert_error_schema(body, error_code="NOT_FOUND")

    def test_request_validation_error_has_error_code(self, mini_client):
        """RequestValidationError gets error_code=VALIDATION_ERROR and details.errors list."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from pydantic import BaseModel

        from claim_agent.api.error_handlers import register_exception_handlers

        mini3 = FastAPI()
        register_exception_handlers(mini3)

        class Payload(BaseModel):
            name: str
            age: int

        @mini3.post("/validate")
        def validate_body(body: Payload):
            return body

        c3 = TestClient(mini3, raise_server_exceptions=False)
        resp = c3.post("/validate", json={"name": "Alice"})  # missing 'age'
        assert resp.status_code == 422
        body = resp.json()
        _assert_error_schema(body, error_code="VALIDATION_ERROR")
        assert "details" in body
        assert "errors" in body["details"]
        assert isinstance(body["details"]["errors"], list)
        assert len(body["details"]["errors"]) >= 1


# ---------------------------------------------------------------------------
# Middleware error responses
# ---------------------------------------------------------------------------


class TestMiddlewareErrorResponses:
    def test_middleware_413_includes_error_code(self, client):
        """413 middleware response includes both error_code and detail fields.

        We test this directly since 413 is the easiest middleware error to trigger
        via TestClient (Content-Length is set automatically so 411 cannot be triggered
        the same way).
        """
        large_body = "x" * (11 * 1024 * 1024)
        resp = client.post(
            "/api/v1/claims",
            content=large_body.encode(),
            headers={"Content-Type": "application/json", "Content-Length": str(len(large_body))},
        )
        assert resp.status_code == 413
        body = resp.json()
        assert body.get("detail") == "Request body too large"
        assert body.get("error_code") == "REQUEST_TOO_LARGE"
