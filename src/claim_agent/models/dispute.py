"""Pydantic models for policyholder dispute handling."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DisputeType(str, Enum):
    """Classification of policyholder dispute."""

    LIABILITY_DETERMINATION = "liability_determination"
    VALUATION_DISAGREEMENT = "valuation_disagreement"
    REPAIR_ESTIMATE = "repair_estimate"
    DEDUCTIBLE_APPLICATION = "deductible_application"


AUTO_RESOLVABLE_DISPUTE_TYPES = frozenset({
    DisputeType.VALUATION_DISAGREEMENT,
    DisputeType.REPAIR_ESTIMATE,
    DisputeType.DEDUCTIBLE_APPLICATION,
})


class DisputeInput(BaseModel):
    """Input payload for a policyholder dispute."""

    claim_id: str = Field(..., description="ID of the existing claim being disputed")
    dispute_type: DisputeType = Field(..., description="Category of the dispute")
    dispute_description: str = Field(
        ..., description="Policyholder's description of why they disagree"
    )
    policyholder_evidence: Optional[str] = Field(
        default=None,
        description="Optional supporting evidence or documentation references from the policyholder",
    )


class DisputeOutput(BaseModel):
    """Output from dispute resolution workflow."""

    claim_id: str = Field(..., description="Claim ID")
    dispute_type: DisputeType = Field(..., description="Dispute category")
    resolution_type: Literal["auto_resolved", "escalated"] = Field(
        ..., description="Whether the dispute was auto-resolved or escalated to a human"
    )
    findings: str = Field(..., description="Summary of analysis findings")
    adjusted_amount: Optional[float] = Field(
        default=None,
        description="Revised payout/estimate amount if adjusted during auto-resolution",
    )
    original_amount: Optional[float] = Field(
        default=None,
        description="Original payout/estimate amount before dispute",
    )
    escalation_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons for escalation when resolution_type is escalated",
    )
    recommended_action: str = Field(
        default="", description="Recommended next steps"
    )
    compliance_notes: list[str] = Field(
        default_factory=list,
        description="Regulatory compliance notes relevant to this dispute",
    )
