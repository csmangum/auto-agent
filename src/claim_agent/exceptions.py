"""Custom exceptions for claim processing."""


class ClaimAgentError(Exception):
    """Base for all claim-agent domain errors."""


class AdapterError(ClaimAgentError):
    """Policy/valuation/repair adapter failure or not implemented."""


class DomainValidationError(ClaimAgentError):
    """Invalid input (domain validation, distinct from Pydantic ValidationError)."""


class ClaimNotFoundError(ClaimAgentError):
    """Claim ID does not exist."""


class InvalidClaimTransitionError(ClaimAgentError):
    """Invalid claim status transition (compliance violation)."""

    def __init__(self, claim_id: str, from_status: str, to_status: str, reason: str):
        self.claim_id = claim_id
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        super().__init__(
            f"Invalid claim transition {claim_id}: {from_status!r} -> {to_status!r} — {reason}"
        )


class BudgetExceededError(ClaimAgentError):
    """Token or LLM call budget exceeded."""


class EscalationError(ClaimAgentError):
    """Mid-workflow escalation (route to review queue)."""


class MidWorkflowEscalation(EscalationError):
    """Raised by escalate_claim tool to halt crew execution and route claim to review queue."""

    def __init__(
        self,
        reason: str,
        indicators: list[str],
        priority: str,
        claim_id: str,
    ):
        self.reason = reason
        self.indicators = indicators
        self.priority = priority
        self.claim_id = claim_id
        super().__init__(f"Mid-workflow escalation: {reason}")


class TokenBudgetExceeded(BudgetExceededError):
    """Raised when a claim exceeds the configured token or LLM call budget."""

    def __init__(self, claim_id: str, total_tokens: int, total_calls: int, message: str):
        self.claim_id = claim_id
        self.total_tokens = total_tokens
        self.total_calls = total_calls
        super().__init__(message)


class ReserveAuthorityError(ClaimAgentError):
    """Reserve amount exceeds actor's authority limit."""

    def __init__(self, amount: float, limit: float, actor_id: str, role: str = "adjuster"):
        self.amount = amount
        self.limit = limit
        self.actor_id = actor_id
        self.role = role
        super().__init__(
            f"Reserve amount ${amount:,.2f} exceeds authority limit ${limit:,.2f} for role '{role}' (actor={actor_id})"
        )


class PaymentAuthorityError(ClaimAgentError):
    """Payment amount exceeds actor's authority limit."""

    def __init__(self, amount: float, limit: float, actor_id: str, role: str = "adjuster"):
        self.amount = amount
        self.limit = limit
        self.actor_id = actor_id
        self.role = role
        super().__init__(
            f"Payment amount ${amount:,.2f} exceeds authority limit ${limit:,.2f} for role '{role}' (actor={actor_id})"
        )
