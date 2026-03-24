"""Tests for rental reimbursement tools."""

import json

import pytest

from claim_agent.tools.rental_logic import (
    check_rental_coverage_impl,
    get_rental_limits_impl,
    process_rental_reimbursement_impl,
)


class TestCheckRentalCoverage:
    """Tests for check_rental_coverage_impl."""

    def test_policy_with_rental_reimbursement(self):
        """Policy with rental_reimbursement returns eligible."""
        result = check_rental_coverage_impl("POL-001")
        data = json.loads(result)
        assert data["eligible"] is True
        assert data["daily_limit"] == 35.0
        assert data["aggregate_limit"] == 1050.0
        assert data["max_days"] == 30

    def test_policy_without_rental_liability_only(self):
        """Liability-only policy returns not eligible."""
        result = check_rental_coverage_impl("POL-002")
        data = json.loads(result)
        assert data["eligible"] is False
        assert data["daily_limit"] is None
        assert "liability" in data["message"].lower() or "does not include" in data["message"].lower()

    def test_policy_comprehensive_infers_eligible(self):
        """Comprehensive coverage without explicit rental infers eligible with defaults."""
        result = check_rental_coverage_impl("POL-009")
        data = json.loads(result)
        assert data["eligible"] is True
        assert data["daily_limit"] == 35.0
        assert data["aggregate_limit"] == 1050.0
        assert data["max_days"] == 30

    def test_invalid_policy_number(self):
        """Invalid policy number returns not eligible."""
        result = check_rental_coverage_impl("")
        data = json.loads(result)
        assert data["eligible"] is False
        assert data["message"] == "Invalid policy number"

    def test_whitespace_only_policy_number(self):
        """Whitespace-only policy number returns not eligible."""
        result = check_rental_coverage_impl("   ")
        data = json.loads(result)
        assert data["eligible"] is False
        assert data["message"] == "Invalid policy number"

    def test_policy_not_found(self):
        """Non-existent policy returns not eligible."""
        result = check_rental_coverage_impl("POL-NONEXISTENT")
        data = json.loads(result)
        assert data["eligible"] is False

    def test_inactive_policy_returns_not_eligible(self):
        """Inactive policy returns not eligible."""
        result = check_rental_coverage_impl("POL-021")
        data = json.loads(result)
        assert data["eligible"] is False
        assert "not active" in data["message"].lower() or "inactive" in data["message"].lower()

    def test_expired_policy_returns_not_eligible(self):
        """Expired policy returns not eligible."""
        result = check_rental_coverage_impl("POL-023")
        data = json.loads(result)
        assert data["eligible"] is False


class TestGetRentalLimits:
    """Tests for get_rental_limits_impl."""

    def test_policy_with_rental_returns_limits(self):
        """Policy with rental_reimbursement returns explicit limits."""
        result = get_rental_limits_impl("POL-001")
        data = json.loads(result)
        assert data["daily_limit"] == 35.0
        assert data["aggregate_limit"] == 1050.0
        assert data["max_days"] == 30

    def test_policy_pol005_custom_limits(self):
        """POL-005 has custom limits (40/1200)."""
        result = get_rental_limits_impl("POL-005")
        data = json.loads(result)
        assert data["daily_limit"] == 40.0
        assert data["aggregate_limit"] == 1200.0

    def test_whitespace_only_policy_number_returns_error(self):
        """Whitespace-only policy number returns error, not defaults."""
        result = get_rental_limits_impl("   ")
        data = json.loads(result)
        assert data["error"] == "Invalid policy number"
        assert data["daily_limit"] is None
        assert data["aggregate_limit"] is None
        assert data["max_days"] is None

    def test_policy_not_found_returns_error(self):
        """Non-existent policy returns error, not defaults."""
        result = get_rental_limits_impl("POL-NONEXISTENT")
        data = json.loads(result)
        assert data["error"] == "Policy not found"
        assert data["daily_limit"] is None
        assert data["aggregate_limit"] is None
        assert data["max_days"] is None

    def test_policy_without_rental_returns_defaults(self):
        """Policy without rental returns compliance defaults."""
        result = get_rental_limits_impl("POL-002")
        data = json.loads(result)
        assert data["daily_limit"] == 35.0
        assert data["aggregate_limit"] == 1050.0
        assert data["max_days"] == 30


class TestProcessRentalReimbursement:
    """Tests for process_rental_reimbursement_impl."""

    def test_valid_reimbursement_succeeds(self):
        """Valid reimbursement within limits is approved."""
        result = process_rental_reimbursement_impl(
            claim_id="CLM-TEST",
            amount=175.0,
            rental_days=5,
            policy_number="POL-001",
        )
        data = json.loads(result)
        assert data["status"] == "approved"
        assert data["amount"] == 175.0
        assert data["reimbursement_id"].startswith("RENT-")

    def test_idempotent_duplicate_returns_same_reimbursement_id(self):
        """Duplicate call with same params returns same reimbursement_id."""
        result1 = process_rental_reimbursement_impl(
            claim_id="CLM-IDEM",
            amount=105.0,
            rental_days=3,
            policy_number="POL-001",
        )
        result2 = process_rental_reimbursement_impl(
            claim_id="CLM-IDEM",
            amount=105.0,
            rental_days=3,
            policy_number="POL-001",
        )
        data1 = json.loads(result1)
        data2 = json.loads(result2)
        assert data1["status"] == "approved"
        assert data2["status"] == "approved"
        assert data1["reimbursement_id"] == data2["reimbursement_id"]
        assert "idempotent" in data2["message"].lower()

    def test_amount_exceeds_daily_limit_fails(self):
        """Amount exceeding daily_limit * days fails."""
        result = process_rental_reimbursement_impl(
            claim_id="CLM-TEST",
            amount=500.0,
            rental_days=5,
            policy_number="POL-001",
        )
        data = json.loads(result)
        assert data["status"] == "failed"
        assert data["reimbursement_id"] == ""
        assert "exceeds" in data["message"].lower()

    def test_amount_exceeds_aggregate_fails(self):
        """Amount exceeding aggregate_limit fails."""
        result = process_rental_reimbursement_impl(
            claim_id="CLM-TEST",
            amount=2000.0,
            rental_days=30,
            policy_number="POL-001",
        )
        data = json.loads(result)
        assert data["status"] == "failed"

    def test_invalid_claim_id_fails(self):
        """Empty claim_id fails."""
        result = process_rental_reimbursement_impl(
            claim_id="",
            amount=100.0,
            rental_days=3,
            policy_number="POL-001",
        )
        data = json.loads(result)
        assert data["status"] == "failed"
        assert "Invalid" in data["message"]

    def test_invalid_amount_fails(self):
        """Negative amount fails."""
        result = process_rental_reimbursement_impl(
            claim_id="CLM-TEST",
            amount=-50.0,
            rental_days=3,
            policy_number="POL-001",
        )
        data = json.loads(result)
        assert data["status"] == "failed"


class TestProcessRentalReimbursementPersistence:
    """DB persistence when ClaimContext is provided."""

    @pytest.fixture(autouse=True)
    def _clear_rental_idempotency_cache(self):
        from claim_agent.tools import rental_logic

        rental_logic._IDEMPOTENCY_CACHE.clear()
        yield

    def test_persists_authorization_when_ctx_provided(self, seeded_temp_db):
        """Rental row is written to the same DB as ClaimRepository."""
        from claim_agent.context import ClaimContext
        from claim_agent.db.rental_repository import RentalAuthorizationRepository

        ctx = ClaimContext.from_defaults(db_path=seeded_temp_db)
        result = process_rental_reimbursement_impl(
            claim_id="CLM-TEST001",
            amount=70.0,
            rental_days=2,
            policy_number="POL-001",
            ctx=ctx,
        )
        data = json.loads(result)
        assert data["status"] == "approved"
        rid = data["reimbursement_id"]
        assert rid.startswith("RENT-")

        repo = RentalAuthorizationRepository(db_path=seeded_temp_db)
        record = repo.get_by_reimbursement_id(rid)
        assert record is not None
        assert record["claim_id"] == "CLM-TEST001"
        assert record["authorized_days"] == 2
        assert record["amount_approved"] == 70.0

    def test_cross_process_idempotency_preserves_reimbursement_id(self, seeded_temp_db):
        """Cache miss + DB lookup returns same reimbursement_id (cross-process idempotency)."""
        from claim_agent.context import ClaimContext

        ctx = ClaimContext.from_defaults(db_path=seeded_temp_db)
        result1 = process_rental_reimbursement_impl(
            claim_id="CLM-TEST001",
            amount=140.0,
            rental_days=4,
            policy_number="POL-001",
            ctx=ctx,
        )
        data1 = json.loads(result1)
        assert data1["status"] == "approved"
        rid1 = data1["reimbursement_id"]
        assert rid1.startswith("RENT-")

        from claim_agent.tools import rental_logic
        rental_logic._IDEMPOTENCY_CACHE.clear()

        ctx2 = ClaimContext.from_defaults(db_path=seeded_temp_db)
        result2 = process_rental_reimbursement_impl(
            claim_id="CLM-TEST001",
            amount=140.0,
            rental_days=4,
            policy_number="POL-001",
            ctx=ctx2,
        )
        data2 = json.loads(result2)
        assert data2["status"] == "approved"
        assert data2["reimbursement_id"] == rid1, "DB lookup should return existing reimbursement_id"
        assert "idempotent" in data2["message"].lower()


class TestRentalToolsWrapper:
    """Test rental_tools.py CrewAI wrappers."""

    def test_check_rental_coverage_wrapper(self):
        """Test check_rental_coverage tool wrapper."""
        from claim_agent.tools.rental_tools import check_rental_coverage

        result = check_rental_coverage.run(policy_number="POL-001")
        data = json.loads(result)
        assert "eligible" in data

    def test_get_rental_limits_wrapper(self):
        """Test get_rental_limits tool wrapper."""
        from claim_agent.tools.rental_tools import get_rental_limits

        result = get_rental_limits.run(policy_number="POL-001")
        data = json.loads(result)
        assert "daily_limit" in data
        assert "aggregate_limit" in data

    def test_process_rental_reimbursement_wrapper(self):
        """Test process_rental_reimbursement tool wrapper."""
        from claim_agent.tools.rental_tools import process_rental_reimbursement

        result = process_rental_reimbursement.run(
            claim_id="CLM-TEST",
            amount=105.0,
            rental_days=3,
            policy_number="POL-001",
        )
        data = json.loads(result)
        assert data["status"] == "approved"
        assert data["reimbursement_id"].startswith("RENT-")
