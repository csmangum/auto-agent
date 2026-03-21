"""Pydantic models for structured workflow crew outputs."""

from typing import TypedDict

from pydantic import BaseModel, Field


class DocumentVerifiedSummary(TypedDict, total=False):
    """Summary of a document checked during SIU verification."""

    type: str
    verified: bool
    findings: list[str]
    recommendation: str


class TotalLossDetails(BaseModel):
    """ACV breakdown and total loss settlement details."""

    acv_base: float | None = Field(
        default=None, description="Base ACV from valuation"
    )
    tax_title_fees: float | None = Field(
        default=None, description="Sales tax, DMV fees, registration"
    )
    acv_total: float | None = Field(
        default=None, description="acv_base + tax_title_fees"
    )
    salvage_deduction: float | None = Field(
        default=None, description="Deduction if owner-retained salvage"
    )
    owner_retain_option: bool = Field(
        default=False, description="Whether owner-retain option was offered"
    )
    comparable_vehicles: list[dict] = Field(
        default_factory=list,
        description="Comparable vehicles used for valuation",
    )
    diminished_value: float | None = Field(
        default=None, description="Diminished value amount if state requires"
    )
    gap_insurance_applied: bool = Field(
        default=False,
        description=(
            "True when policy includes gap and payout is below loan/lease balance "
            "(carrier coordination triggered or required)"
        ),
    )
    gap_claim_id: str | None = Field(
        default=None, description="Gap carrier reference after submission"
    )
    gap_claim_status: str | None = Field(
        default=None, description="Carrier status: submitted, approved_pending_payment, etc."
    )
    gap_shortfall_amount: float | None = Field(
        default=None, description="Loan/lease balance minus auto payout (before gap)"
    )
    gap_approved_amount: float | None = Field(
        default=None, description="Amount gap carrier approved toward shortfall"
    )
    gap_remaining_shortfall: float | None = Field(
        default=None,
        description="Balance owed after gap decision (partial pay or denial)",
    )
    gap_denial_reason: str | None = Field(
        default=None, description="Reason when gap claim denied or partially denied"
    )


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
    total_loss_details: TotalLossDetails | None = Field(
        default=None,
        description="ACV breakdown, comparables, tax/title/fees, salvage deduction",
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


class ReopenedWorkflowOutput(BaseModel):
    """Structured output from Reopened crew: validated reason, prior claim summary, target routing."""

    target_claim_type: str = Field(
        ...,
        description="Routed claim type: partial_loss, total_loss, or bodily_injury",
    )
    reopening_reason_validated: bool = Field(
        ..., description="Whether the reopening reason was validated"
    )
    prior_claim_id: str | None = Field(
        default=None, description="ID of the prior settled claim"
    )
    prior_claim_summary: str | None = Field(
        default=None, description="Brief summary of prior claim (type, status, payout)"
    )
    reopening_reason: str | None = Field(
        default=None, description="Validated reopening reason (e.g., new damage, policyholder appeal)"
    )


class BIWorkflowOutput(BaseModel):
    """Structured output from Bodily Injury crew final task."""

    payout_amount: float = Field(
        ..., description="Proposed BI settlement amount (insurance payment)"
    )
    medical_charges: float | None = Field(
        default=None, description="Total medical specials (post-audit if applicable)"
    )
    pain_suffering: float | None = Field(
        default=None, description="Pain and suffering component"
    )
    injury_severity: str | None = Field(
        default=None, description="Severity classification"
    )
    claim_id: str | None = Field(default=None, description="Claim ID")
    policy_bi_limit_per_person: float | None = Field(
        default=None, description="Policy BI per-person limit"
    )
    policy_bi_limit_per_accident: float | None = Field(
        default=None, description="Policy BI per-accident limit"
    )
    loss_of_earnings: float | None = Field(
        default=None, description="Recommended wage loss amount if applicable"
    )
    pip_medpay_exhausted: bool | None = Field(
        default=None, description="Whether PIP/MedPay exhaustion prerequisite met"
    )
    cms_reporting_required: bool | None = Field(
        default=None, description="Whether CMS/Medicare reporting required"
    )
    minor_court_approval_required: bool | None = Field(
        default=None, description="Whether court approval required for minor/incapacitated"
    )
    minor_court_approval_obtained: bool | None = Field(
        default=None,
        description="Whether court approval already obtained (claim data may also set minor_court_approval_obtained)",
    )
    structured_settlement_offered: bool | None = Field(
        default=None, description="Whether structured settlement option offered"
    )


class SIUInvestigationResult(BaseModel):
    """Structured output from SIU Case Manager final task."""

    findings_summary: str = Field(
        default="",
        description="Synthesis of document verification and records investigation findings",
    )
    recommendation: str = Field(
        default="",
        description="Outcome: closed_no_fraud, closed_fraud_confirmed, or referred",
    )
    case_status: str = Field(
        default="",
        description="Final SIU case status: open, investigating, referred, or closed",
    )
    state_report_filed: bool = Field(
        default=False,
        description="Whether a fraud report was filed with the state bureau",
    )
    documents_verified: list[DocumentVerifiedSummary] = Field(
        default_factory=list,
        description="Summary of documents checked and verification status",
    )
    prior_claims_summary: str | None = Field(
        default=None,
        description="Summary of prior claims, fraud flags, SIU cases on VIN/policy",
    )
    tool_failures_noted: str | None = Field(
        default=None,
        description="Any tool failures from prior agents that affected the investigation",
    )
