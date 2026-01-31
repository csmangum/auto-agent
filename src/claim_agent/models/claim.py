"""Pydantic models for claim input, output, and workflow state."""

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """Classification of claim workflow."""

    NEW = "new"
    DUPLICATE = "duplicate"
    TOTAL_LOSS = "total_loss"
    PARTIAL_LOSS = "partial_loss"


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


class RepairShopAssignment(BaseModel):
    """Repair shop assignment details for partial loss claims."""

    shop_id: str = Field(..., description="Assigned repair shop ID")
    shop_name: str = Field(..., description="Repair shop name")
    address: str = Field(default="", description="Shop address")
    phone: str = Field(default="", description="Shop phone number")
    estimated_start_date: Optional[str] = Field(
        default=None, description="Estimated repair start date (YYYY-MM-DD)"
    )
    estimated_completion_date: Optional[str] = Field(
        default=None, description="Estimated repair completion date (YYYY-MM-DD)"
    )


class PartsOrderItem(BaseModel):
    """Individual part in a parts order."""

    part_id: str = Field(..., description="Part catalog ID")
    part_name: str = Field(..., description="Part name")
    quantity: int = Field(default=1, description="Quantity ordered")
    part_type: Literal["oem", "aftermarket", "refurbished"] = Field(
        default="aftermarket", description="Part type preference"
    )
    unit_price: float = Field(..., description="Price per unit")
    total_price: float = Field(..., description="Total price for this item")
    availability: str = Field(default="in_stock", description="Availability status")
    lead_time_days: int = Field(default=1, description="Expected days to receive")


class PartsOrder(BaseModel):
    """Parts order for partial loss repair."""

    order_id: str = Field(..., description="Parts order ID")
    claim_id: str = Field(..., description="Associated claim ID")
    items: list[PartsOrderItem] = Field(default_factory=list, description="Ordered parts")
    total_parts_cost: float = Field(default=0.0, description="Total cost of parts")
    order_status: Literal["pending", "ordered", "shipped", "delivered"] = Field(
        default="pending", description="Order status"
    )
    estimated_delivery_date: Optional[str] = Field(
        default=None, description="Estimated delivery date (YYYY-MM-DD)"
    )


class RepairEstimate(BaseModel):
    """Repair estimate for partial loss claims."""

    labor_hours: float = Field(default=0.0, description="Estimated labor hours")
    labor_cost: float = Field(default=0.0, description="Estimated labor cost")
    parts_cost: float = Field(default=0.0, description="Estimated parts cost")
    total_estimate: float = Field(default=0.0, description="Total repair estimate")
    deductible: float = Field(default=0.0, description="Policy deductible")
    customer_pays: float = Field(default=0.0, description="Amount customer pays (deductible)")
    insurance_pays: float = Field(default=0.0, description="Amount insurance pays")


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
    routing_confidence: Optional[float] = Field(
        default=None, description="Router confidence 0.0-1.0"
    )
    escalation_reasons: list[str] = Field(
        default_factory=list, description="Reasons for escalation"
    )
    needs_review: bool = Field(default=False, description="Claim needs human review")
    escalation_priority: Optional[str] = Field(
        default=None, description="Escalation priority: low, medium, high, critical"
    )
    # Partial loss specific fields
    repair_shop: Optional[RepairShopAssignment] = Field(
        default=None, description="Assigned repair shop for partial loss"
    )
    parts_order: Optional[PartsOrder] = Field(
        default=None, description="Parts order for partial loss repair"
    )
    repair_estimate: Optional[RepairEstimate] = Field(
        default=None, description="Repair estimate details"
    )
