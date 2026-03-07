"""Pydantic models for structured workflow crew outputs."""

from pydantic import BaseModel, Field


class TotalLossWorkflowOutput(BaseModel):
    """Structured output from Total Loss crew final task."""

    payout_amount: float = Field(
        ..., description="Net payout (vehicle value minus deductible)"
    )
    vehicle_value: float | None = Field(
        default=None, description="ACV from valuation"
    )
    deductible: float | None = Field(
        default=None, description="Policy deductible applied"
    )
    calculation: str | None = Field(
        default=None, description="One-line calculation"
    )


class PartialLossWorkflowOutput(BaseModel):
    """Structured output from Partial Loss crew final task."""

    payout_amount: float = Field(
        ..., description="Insurance payment amount (insurance_pays)"
    )
    authorization_id: str | None = Field(
        default=None, description="Repair authorization ID"
    )
    total_estimate: float | None = Field(
        default=None, description="Total repair estimate"
    )
