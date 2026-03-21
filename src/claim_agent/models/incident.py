"""Pydantic models for incident-level claim grouping.

One incident can involve multiple vehicles and multiple claimants.
Claims are linked to incidents for coordinated handling.
"""

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from claim_agent.models.claim import Attachment
from claim_agent.models.party import ClaimPartyInput


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
    background_scheduling: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Per-claim background scheduling result when async=true. "
            "Values: 'scheduled' or 'capacity_exceeded'."
        ),
    )


class IncidentRecord(BaseModel):
    """Incident row as stored in the database (GET incident detail)."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Incident ID")
    incident_date: str = Field(..., description="Date of incident (storage format)")
    incident_description: Optional[str] = Field(default=None, description="Incident narrative")
    loss_state: Optional[str] = Field(
        default=None,
        description="State/jurisdiction where the loss occurred",
    )
    created_at: Optional[str] = Field(default=None, description="Row creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="Row last update timestamp")

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_timestamps(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)


class IncidentDetailResponse(BaseModel):
    """Response for GET /incidents/{incident_id}: incident metadata and linked claims."""

    incident: IncidentRecord = Field(..., description="Incident record")
    claims: list[dict[str, Any]] = Field(
        ...,
        description="Full claim rows for all claims linked to this incident",
    )


class RelatedClaimsResponse(BaseModel):
    """Response for GET /claims/{claim_id}/related."""

    claim_id: str = Field(..., description="Claim ID from the path")
    related_claim_ids: list[str] = Field(
        default_factory=list,
        description="Other claim IDs linked to this claim (sorted)",
    )


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

    @model_validator(mode="after")
    def validate_no_self_link(self) -> "ClaimLinkInput":
        if self.claim_id_a == self.claim_id_b:
            raise ValueError("A claim cannot be linked to itself (claim_id_a must differ from claim_id_b)")
        return self


class ClaimantDemandInput(BaseModel):
    """Single claimant demand for BI allocation."""

    claimant_id: Optional[str] = Field(
        default=None, description="Claimant or party identifier",
    )
    party_id: Optional[str] = Field(
        default=None, description="Alternate identifier (used if claimant_id not set)",
    )
    demanded_amount: float = Field(..., ge=0, description="Demanded amount in dollars")
    injury_severity: Optional[float] = Field(
        default=None,
        ge=0.1,
        le=10.0,
        description="Severity weight 1-10 for severity_weighted allocation",
    )


class BIAllocationInput(BaseModel):
    """Input for BI coverage limit allocation across multiple claimants.

    When total BI demands exceed per_accident limits, allocate proportionally.
    """

    claim_id: str = Field(..., description="Claim ID (policy with BI limits)")
    claimant_demands: list[ClaimantDemandInput] = Field(
        ...,
        description="List of claimant demands with demanded_amount, claimant_id/party_id, injury_severity?",
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
