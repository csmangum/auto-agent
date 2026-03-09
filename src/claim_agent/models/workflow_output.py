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
    claim_id: str | None = Field(
        default=None, description="Claim ID (from generate_repair_authorization)"
    )
    shop_id: str | None = Field(
        default=None, description="Repair shop ID (from generate_repair_authorization)"
    )
    shop_name: str | None = Field(
        default=None, description="Repair shop name (from generate_repair_authorization)"
    )
    shop_phone: str | None = Field(
        default=None, description="Repair shop phone (from generate_repair_authorization)"
    )
    authorized_amount: float | None = Field(
        default=None, description="Authorized repair amount (from generate_repair_authorization)"
    )
    shop_webhook_url: str | None = Field(
        default=None, description="Shop-specific webhook URL for notifications"
    )
    estimated_repair_days: int | None = Field(
        default=None,
        description="Estimated repair duration from shop assignment (for rental crew)",
    )
