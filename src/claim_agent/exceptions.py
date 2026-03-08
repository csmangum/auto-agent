"""Custom exceptions for claim processing."""


class ClaimAgentError(Exception):
    """Base for all claim-agent domain errors."""


class AdapterError(ClaimAgentError):
    """Policy/valuation/repair adapter failure or not implemented."""


class ValidationError(ClaimAgentError):
    """Invalid input (domain validation, distinct from Pydantic ValidationError)."""


class ClaimNotFoundError(ClaimAgentError):
    """Claim ID does not exist."""


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
