"""Pydantic models for denial and coverage dispute handling."""

from pydantic import BaseModel, Field


class DenialInput(BaseModel):
    """Input payload for denial/coverage dispute workflow."""

    claim_id: str = Field(..., description="ID of the denied claim")
    denial_reason: str = Field(
        ...,
        description="Stated reason for the denial (from adjuster or system)",
        max_length=4096,
    )
    policyholder_evidence: str | None = Field(
        default=None,
        description="Optional evidence or argument from policyholder",
        max_length=8192,
    )
