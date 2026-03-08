"""Custom exceptions for claim processing."""


class MidWorkflowEscalation(Exception):
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


class TokenBudgetExceeded(Exception):
    """Raised when a claim exceeds the configured token or LLM call budget."""

    def __init__(self, claim_id: str, total_tokens: int, total_calls: int, message: str):
        self.claim_id = claim_id
        self.total_tokens = total_tokens
        self.total_calls = total_calls
        super().__init__(message)
