"""Pydantic models for claim input, output, and workflow state."""

from datetime import date
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from claim_agent.models.party import ClaimPartyInput


class AttachmentType(str, Enum):
    """Type of claim attachment."""

    PHOTO = "photo"
    PDF = "pdf"
    ESTIMATE = "estimate"
    OTHER = "other"


class Attachment(BaseModel):
    """Attachment metadata: url, type, optional description."""

    url: str = Field(..., description="URL to the file (S3, local path, or external)")
    type: AttachmentType = Field(..., description="Attachment type: photo, pdf, estimate, other")
    description: Optional[str] = Field(default=None, description="Optional description of the attachment")


class ClaimType(str, Enum):
    """Classification of claim workflow."""

    NEW = "new"
    DUPLICATE = "duplicate"
    TOTAL_LOSS = "total_loss"
    FRAUD = "fraud"
    PARTIAL_LOSS = "partial_loss"
    BODILY_INJURY = "bodily_injury"
    REOPENED = "reopened"


class RouterOutput(BaseModel):
    """Structured router output: claim_type, confidence (0.0-1.0), reasoning."""

    claim_type: str = Field(
        ...,
        description="Classification: new, duplicate, total_loss, fraud, partial_loss, bodily_injury, or reopened",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence in classification from 0.0 (low) to 1.0 (high)",
    )
    reasoning: str = Field(
        default="",
        description="Brief reasoning for the classification",
    )


class ClaimInput(BaseModel):
    """Input payload for claim processing."""

    policy_number: str = Field(..., description="Insurance policy number")
    vin: str = Field(..., description="Vehicle identification number")
    vehicle_year: int = Field(..., description="Year of vehicle")
    vehicle_make: str = Field(..., description="Vehicle manufacturer")
    vehicle_model: str = Field(..., description="Vehicle model")
    incident_date: date = Field(..., description="Date of incident (YYYY-MM-DD)")
    incident_description: str = Field(..., description="Description of the incident")
    damage_description: str = Field(..., description="Description of vehicle damage")
    estimated_damage: Optional[float] = Field(
        default=None, description="Estimated repair cost in dollars"
    )
    attachments: list[Attachment] = Field(
        default_factory=list,
        description="Optional attachments (photos, PDFs, estimates)",
    )
    claim_type: Optional[Literal["new", "duplicate", "total_loss", "partial_loss", "bodily_injury", "fraud", "reopened"]] = Field(
        default=None,
        description="Pre-determined claim type (e.g., from reviewer override). Only trusted when set via supervisor/reviewer paths; intake endpoints should not accept this.",
    )
    loss_state: Optional[str] = Field(
        default=None,
        description="State/jurisdiction where the loss occurred (e.g., California, Texas, Florida, New York). Used for state-specific compliance rules, deadlines, and total loss thresholds.",
    )
    parties: Optional[list[ClaimPartyInput]] = Field(
        default=None,
        description="Optional claim parties (claimant, policyholder, witness, attorney, provider, lienholder).",
    )
    incident_id: Optional[str] = Field(
        default=None,
        description="Optional incident ID when claim is part of a multi-vehicle incident.",
    )


class LiabilityDeterminationOutput(BaseModel):
    """Structured output from liability determination crew."""

    liability_percentage: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Insured's share of fault (0-100). None if unclear.",
    )
    liability_basis: str = Field(
        default="",
        description="Reasoning or source for the liability determination.",
    )
    fault_determination: str = Field(
        ...,
        description="at_fault | not_at_fault | unclear",
    )
    third_party_identified: bool = Field(
        default=False,
        description="Whether a third party can be identified for subrogation.",
    )
    recovery_eligible: bool = Field(
        default=False,
        description="Whether subrogation recovery is eligible per state rules.",
    )


class ClaimOutput(BaseModel):
    """Output from claim processing."""

    claim_id: Optional[str] = Field(default=None, description="Assigned claim ID")
    claim_type: ClaimType = Field(..., description="Classified claim type")
    status: str = Field(..., description="Claim status (e.g., open, closed, duplicate)")
    actions_taken: list[str] = Field(
        default_factory=list, description="Summary of actions performed"
    )
    payout_amount: Optional[float] = Field(
        default=None, description="Settlement or insurance payment amount for payout-ready claims"
    )
    liability_percentage: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Insured's share of fault (0-100) from liability determination.",
    )
    liability_basis: Optional[str] = Field(
        default=None,
        description="Reasoning for liability determination.",
    )
    reserve_amount: Optional[float] = Field(
        default=None, description="Reserve amount (estimated ultimate cost) when relevant"
    )
    message: Optional[str] = Field(default=None, description="Human-readable summary")
    raw_result: Optional[dict[str, Any]] = Field(
        default=None, description="Full crew output for debugging"
    )


class EscalationOutput(BaseModel):
    """Output from escalation evaluation for human-in-the-loop review."""

    claim_id: str = Field(..., description="Claim ID")
    needs_review: bool = Field(..., description="Whether claim requires human review")
    escalation_reasons: list[str] = Field(
        default_factory=list, description="Reasons for escalation"
    )
    priority: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Escalation priority: low, medium, high, critical"
    )
    recommended_action: str = Field(
        default="", description="Recommended action for reviewer"
    )
    fraud_indicators: list[str] = Field(
        default_factory=list, description="Detected fraud indicators"
    )
