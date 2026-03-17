"""Pydantic models for incident-level claim grouping.

One incident can involve multiple vehicles and multiple claimants.
Claims are linked to incidents for coordinated handling.
"""

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from claim_agent.models.claim import Attachment
from claim_agent.models.party import ClaimPartyInput


class ClaimLinkType(str, Enum):
    """Type of relationship between two claims."""

    SAME_INCIDENT = "same_incident"
    OPPOSING_CARRIER = "opposing_carrier"
    SUBROGATION = "subrogation"
    CROSS_CARRIER = "cross_carrier"


class VehicleClaimInput(BaseModel):
    """Single-vehicle claim input within an incident.

    Same shape as ClaimInput but used when submitting multiple vehicles
    as part of one incident. Each vehicle becomes a separate claim.
    """

    policy_number: str = Field(..., description="Insurance policy number")
    vin: str = Field(..., description="Vehicle identification number")
    vehicle_year: int = Field(..., description="Year of vehicle")
    vehicle_make: str = Field(..., description="Vehicle manufacturer")
    vehicle_model: str = Field(..., description="Vehicle model")
    damage_description: str = Field(..., description="Description of vehicle damage")
    estimated_damage: Optional[float] = Field(
        default=None, description="Estimated repair cost in dollars"
    )
    attachments: list[Attachment] = Field(
        default_factory=list,
        description="Optional attachments (photos, PDFs, estimates)",
    )
    loss_state: Optional[str] = Field(
        default=None,
        description="State/jurisdiction where the loss occurred",
    )
    parties: Optional[list[ClaimPartyInput]] = Field(
        default=None,
        description="Claim parties (claimant, policyholder, etc.)",
    )


class IncidentInput(BaseModel):
    """Input for creating an incident with multiple vehicle claims.

    One incident (e.g., 2-car accident) can produce multiple claims
    (one per vehicle/policy). Use this for multi-vehicle submissions.
    """

    incident_date: date = Field(..., description="Date of incident (YYYY-MM-DD)")
    incident_description: str = Field(
        ..., description="Description of the incident (applies to all vehicles)"
    )
    loss_state: Optional[str] = Field(
        default=None,
        description="State/jurisdiction where the loss occurred",
    )
    vehicles: list[VehicleClaimInput] = Field(
        ...,
        min_length=1,
        description="One or more vehicles involved. Each becomes a separate claim.",
    )


class IncidentOutput(BaseModel):
    """Output from incident creation."""

    incident_id: str = Field(..., description="Assigned incident ID")
    claim_ids: list[str] = Field(
        default_factory=list,
        description="Claim IDs created for each vehicle",
    )
    message: Optional[str] = Field(default=None, description="Human-readable summary")


class ClaimLinkInput(BaseModel):
    """Input for linking two claims (e.g., cross-carrier coordination)."""

    claim_id_a: str = Field(..., description="First claim ID")
    claim_id_b: str = Field(..., description="Second claim ID")
    link_type: Literal[
        "same_incident", "opposing_carrier", "subrogation", "cross_carrier"
    ] = Field(..., description="Type of relationship")
    opposing_carrier: Optional[str] = Field(
        default=None,
        description="Carrier name when link_type is opposing_carrier or cross_carrier",
    )
    notes: Optional[str] = Field(default=None, description="Optional notes")


class BIAllocationInput(BaseModel):
    """Input for BI coverage limit allocation across multiple claimants.

    When total BI demands exceed per_accident limits, allocate proportionally.
    """

    claim_id: str = Field(..., description="Claim ID (policy with BI limits)")
    claimant_demands: list[dict] = Field(
        ...,
        description="List of {claimant_id/party_id, demanded_amount, injury_severity?}",
    )
    bi_per_accident_limit: float = Field(
        ...,
        ge=0,
        description="Policy BI per-accident limit",
    )
    allocation_method: Literal["proportional", "severity_weighted", "equal"] = Field(
        default="proportional",
        description="Allocation method when demands exceed limit",
    )


class BIAllocationResult(BaseModel):
    """Result of BI limit allocation."""

    claim_id: str = Field(..., description="Claim ID")
    total_demanded: float = Field(..., ge=0, description="Sum of all demands")
    limit: float = Field(..., ge=0, description="Per-accident limit")
    allocations: list[dict] = Field(
        default_factory=list,
        description="{claimant_id, demanded, allocated, shortfall} per claimant",
    )
    total_allocated: float = Field(..., ge=0, description="Sum of allocated amounts")
    limit_exceeded: bool = Field(
        ...,
        description="True if total_demanded > limit (allocation applied)",
    )
