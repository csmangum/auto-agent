"""Pydantic models for denial and coverage dispute handling."""

from pydantic import BaseModel, Field

from claim_agent.utils.sanitization import MAX_DENIAL_REASON, MAX_POLICYHOLDER_EVIDENCE


class DenialInput(BaseModel):
    """Input payload for denial/coverage dispute workflow."""

    claim_id: str = Field(..., description="ID of the denied claim")
    denial_reason: str = Field(
        ...,
        min_length=1,
        description="Stated reason for the denial (from adjuster or system)",
        max_length=MAX_DENIAL_REASON,
    )
    policyholder_evidence: str | None = Field(
        default=None,
        description="Optional evidence or argument from policyholder",
        max_length=MAX_POLICYHOLDER_EVIDENCE,
    )
