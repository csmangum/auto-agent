"""Unit tests for claim_agent domain exceptions."""

from claim_agent.exceptions import (
    AdapterError,
    BudgetExceededError,
    ClaimAgentError,
    ClaimNotFoundError,
    DomainValidationError,
    EscalationError,
    InvalidClaimTransitionError,
    MidWorkflowEscalation,
    PaymentAuthorityError,
    PaymentNotFoundError,
    ReserveAuthorityError,
    TokenBudgetExceeded,
)


class TestClaimAgentError:
    """Base exception hierarchy."""

    def test_claim_agent_error_is_exception(self):
        err = ClaimAgentError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"

    def test_adapter_error_inherits(self):
        err = AdapterError("policy lookup failed")
        assert isinstance(err, ClaimAgentError)
        assert "policy lookup failed" in str(err)

    def test_domain_validation_error_inherits(self):
        err = DomainValidationError("invalid vin")
        assert isinstance(err, ClaimAgentError)

    def test_claim_not_found_error_inherits(self):
        err = ClaimNotFoundError("claim missing")
        assert isinstance(err, ClaimAgentError)

    def test_budget_exceeded_error_inherits(self):
        err = BudgetExceededError("over budget")
        assert isinstance(err, ClaimAgentError)

    def test_escalation_error_inherits(self):
        err = EscalationError("escalate")
        assert isinstance(err, ClaimAgentError)

    def test_payment_not_found_error_inherits(self):
        err = PaymentNotFoundError("payment missing")
        assert isinstance(err, ClaimAgentError)


class TestInvalidClaimTransitionError:
    def test_attributes(self):
        err = InvalidClaimTransitionError(
            claim_id="CLM-001",
            from_status="pending",
            to_status="closed",
            reason="missing required",
        )
        assert err.claim_id == "CLM-001"
        assert err.from_status == "pending"
        assert err.to_status == "closed"
        assert err.reason == "missing required"

    def test_message_format(self):
        err = InvalidClaimTransitionError(
            claim_id="CLM-001",
            from_status="pending",
            to_status="closed",
            reason="missing required",
        )
        assert "CLM-001" in str(err)
        assert "pending" in str(err)
        assert "closed" in str(err)
        assert "missing required" in str(err)


class TestMidWorkflowEscalation:
    def test_attributes(self):
        err = MidWorkflowEscalation(
            reason="fraud indicators",
            indicators=["staged", "exaggerated"],
            priority="high",
            claim_id="CLM-002",
        )
        assert err.reason == "fraud indicators"
        assert err.indicators == ["staged", "exaggerated"]
        assert err.priority == "high"
        assert err.claim_id == "CLM-002"

    def test_inherits_escalation_error(self):
        err = MidWorkflowEscalation(
            reason="x", indicators=[], priority="low", claim_id="CLM-003"
        )
        assert isinstance(err, EscalationError)
        assert isinstance(err, ClaimAgentError)


class TestTokenBudgetExceeded:
    def test_attributes(self):
        err = TokenBudgetExceeded(
            claim_id="CLM-004",
            total_tokens=50000,
            total_calls=100,
            message="Budget exceeded",
        )
        assert err.claim_id == "CLM-004"
        assert err.total_tokens == 50000
        assert err.total_calls == 100
        assert str(err) == "Budget exceeded"

    def test_inherits_budget_exceeded(self):
        err = TokenBudgetExceeded(
            claim_id="CLM-005", total_tokens=0, total_calls=0, message=""
        )
        assert isinstance(err, BudgetExceededError)


class TestReserveAuthorityError:
    def test_attributes(self):
        err = ReserveAuthorityError(
            amount=10000.0,
            limit=5000.0,
            actor_id="adj-001",
            role="adjuster",
        )
        assert err.amount == 10000.0
        assert err.limit == 5000.0
        assert err.actor_id == "adj-001"
        assert err.role == "adjuster"

    def test_message_format(self):
        err = ReserveAuthorityError(
            amount=10000.0,
            limit=5000.0,
            actor_id="adj-001",
            role="adjuster",
        )
        assert "10,000" in str(err)
        assert "5,000" in str(err)
        assert "adjuster" in str(err)
        assert "adj-001" in str(err)

    def test_default_role(self):
        err = ReserveAuthorityError(
            amount=100.0, limit=50.0, actor_id="x"
        )
        assert err.role == "adjuster"


class TestPaymentAuthorityError:
    def test_attributes(self):
        err = PaymentAuthorityError(
            amount=1000.0,
            limit=500.0,
            actor_id="adj-002",
            role="supervisor",
        )
        assert err.amount == 1000.0
        assert err.limit == 500.0
        assert err.actor_id == "adj-002"
        assert err.role == "supervisor"

    def test_message_format(self):
        err = PaymentAuthorityError(
            amount=1000.0,
            limit=500.0,
            actor_id="adj-002",
            role="supervisor",
        )
        assert "1,000" in str(err)
        assert "500" in str(err)
        assert "supervisor" in str(err)
