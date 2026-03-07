"""Custom exceptions for claim processing."""


class MidWorkflowEscalation(Exception):
    """Raised by escalate_claim tool to halt crew execution and route claim to review queue."""

    def __init__(
        self,
        reason: str,
        indicators: list[str],
        priority: str,
        claim_id: str,
        partial_output: str | None = None,
    ):
        self.reason = reason
        self.indicators = indicators
        self.priority = priority
        self.claim_id = claim_id
        self.partial_output = partial_output
        super().__init__(f"Mid-workflow escalation: {reason}")
