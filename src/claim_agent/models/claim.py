"""Pydantic models for claim input, output, and workflow state."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """Classification of claim workflow."""

    NEW = "new"
    DUPLICATE = "duplicate"
    TOTAL_LOSS = "total_loss"


class ClaimInput(BaseModel):
    """Input payload for claim processing."""

    policy_number: str = Field(..., description="Insurance policy number")
    vin: str = Field(..., description="Vehicle identification number")
    vehicle_year: int = Field(..., description="Year of vehicle")
    vehicle_make: str = Field(..., description="Vehicle manufacturer")
    vehicle_model: str = Field(..., description="Vehicle model")
    incident_date: str = Field(..., description="Date of incident (YYYY-MM-DD)")
    incident_description: str = Field(..., description="Description of the incident")
    damage_description: str = Field(..., description="Description of vehicle damage")
    estimated_damage: Optional[float] = Field(
        default=None, description="Estimated repair cost in dollars"
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
        default=None, description="Settlement amount if total loss"
    )
    message: Optional[str] = Field(default=None, description="Human-readable summary")
    raw_result: Optional[dict[str, Any]] = Field(
        default=None, description="Full crew output for debugging"
    )


class WorkflowState(BaseModel):
    """Shared state passed between tasks in a workflow."""

    claim_input: ClaimInput
    claim_type: Optional[ClaimType] = None
    validation_passed: bool = False
    policy_valid: bool = False
    claim_id: Optional[str] = None
    similar_claims: list[dict[str, Any]] = Field(default_factory=list)
    similarity_score: Optional[float] = None
    is_duplicate: bool = False
    vehicle_value: Optional[float] = None
    damage_estimate: Optional[float] = None
    total_loss: bool = False
    payout_amount: Optional[float] = None
    report_generated: bool = False
