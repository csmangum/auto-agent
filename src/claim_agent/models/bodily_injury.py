"""Pydantic models for Bodily Injury workflow: treatment timeline, bills, liens, PIP/MedPay, CMS, minor settlement, structured settlement."""

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LienType(str, Enum):
    """Type of medical or government lien."""

    HOSPITAL = "hospital"
    PHYSICIAN = "physician"
    MEDICARE = "medicare"
    MEDICAID = "medicaid"
    WORKERS_COMP = "workers_comp"
    ERISA = "erisa"
    OTHER = "other"


class ProviderBill(BaseModel):
    """Individual provider bill for medical bill auditing."""

    provider_name: str = Field(..., description="Provider or facility name")
    provider_npi: Optional[str] = Field(default=None, description="NPI if available")
    date_of_service: date = Field(..., description="Date of service")
    diagnosis_codes: list[str] = Field(
        default_factory=list, description="ICD-10 diagnosis codes"
    )
    procedure_codes: list[str] = Field(
        default_factory=list, description="CPT/HCPCS procedure codes"
    )
    billed_amount: float = Field(..., ge=0, description="Amount billed")
    allowed_amount: Optional[float] = Field(
        default=None, ge=0, description="Fee-schedule or negotiated allowed amount"
    )
    related_to_accident: bool = Field(
        default=True, description="Whether treatment is accident-related"
    )
    audit_notes: Optional[str] = Field(
        default=None, description="Audit findings (duplicate, excessive, unrelated)"
    )


class TreatmentEvent(BaseModel):
    """Single treatment event in the injury timeline."""

    event_date: date = Field(..., description="Date of treatment")
    provider: str = Field(..., description="Provider or facility")
    treatment_type: str = Field(
        ..., description="ER, office visit, PT, surgery, imaging, etc."
    )
    diagnosis: Optional[str] = Field(default=None, description="Diagnosis or procedure")
    charges: float = Field(default=0, ge=0, description="Charges for this event")


class TreatmentTimeline(BaseModel):
    """Injury treatment timeline for settlement valuation.

    Treatment duration affects settlement value: longer treatment suggests
    more severe injury and higher non-economic damages.
    """

    incident_date: date = Field(..., description="Date of accident")
    first_treatment_date: Optional[date] = Field(
        default=None, description="Date of first medical treatment"
    )
    last_treatment_date: Optional[date] = Field(
        default=None, description="Date of last medical treatment"
    )
    treatment_duration_days: Optional[int] = Field(
        default=None, ge=0, description="Days from first to last treatment"
    )
    events: list[TreatmentEvent] = Field(
        default_factory=list, description="Chronological treatment events"
    )
    total_charges: float = Field(default=0, ge=0, description="Sum of all charges")


class LienRecord(BaseModel):
    """Medical or government lien to be satisfied from settlement."""

    lien_type: LienType = Field(..., description="Type of lien")
    holder_name: str = Field(..., description="Lienholder (provider, CMS, state agency)")
    amount: float = Field(..., ge=0, description="Lien amount")
    claim_id: Optional[str] = Field(default=None, description="Conditional payment ID if applicable")
    must_satisfy_before_settlement: bool = Field(
        default=True, description="Whether lien must be paid from settlement"
    )


class PIPMedPayExhaustion(BaseModel):
    """PIP/MedPay first-party medical coverage exhaustion status.

    BI liability settlement typically requires PIP/MedPay exhaustion in
    no-fault states (FL, NY, etc.) or when claimant has first-party medical.
    """

    has_pip_medpay: bool = Field(
        default=False, description="Whether claimant has PIP or MedPay coverage"
    )
    pip_medpay_limit: Optional[float] = Field(
        default=None, ge=0, description="Policy limit for PIP/MedPay"
    )
    amount_paid: Optional[float] = Field(
        default=None, ge=0, description="Amount already paid under PIP/MedPay"
    )
    exhausted: bool = Field(
        default=False, description="Whether PIP/MedPay is exhausted"
    )
    bi_settlement_allowed: bool = Field(
        default=True,
        description="Whether BI settlement can proceed (exhausted or N/A)",
    )
    notes: Optional[str] = Field(default=None, description="State-specific rules applied")


class CMSReportingStatus(BaseModel):
    """CMS/Medicare reporting status for MMSEA Section 111.

    Settlements >$750 involving Medicare beneficiaries require reporting.
    """

    claimant_medicare_eligible: bool = Field(
        default=False, description="Whether claimant is Medicare beneficiary"
    )
    settlement_amount: float = Field(default=0, ge=0, description="Settlement amount")
    reporting_threshold: float = Field(
        default=750, description="CMS reporting threshold (default $750)"
    )
    reporting_required: bool = Field(
        default=False, description="Whether Section 111 reporting is required"
    )
    conditional_payment_amount: Optional[float] = Field(
        default=None, ge=0, description="Medicare conditional payment amount to recover"
    )
    msa_required: bool = Field(
        default=False,
        description="Whether Medicare Set-Aside is required for future medicals",
    )
    reporting_completed: bool = Field(
        default=False, description="Whether reporting has been completed"
    )


class MinorSettlementStatus(BaseModel):
    """Minor or incapacitated claimant settlement approval status.

    Many states require court approval for settlements involving minors
    or incapacitated claimants.
    """

    claimant_is_minor: bool = Field(
        default=False, description="Whether claimant is under 18"
    )
    claimant_incapacitated: bool = Field(
        default=False, description="Whether claimant is legally incapacitated"
    )
    guardian_appointed: bool = Field(
        default=False, description="Whether guardian/conservator is appointed"
    )
    court_approval_required: bool = Field(
        default=False, description="Whether court approval is required"
    )
    court_approval_obtained: bool = Field(
        default=False, description="Whether court has approved settlement"
    )
    state: Optional[str] = Field(
        default=None, description="State jurisdiction for court approval rules"
    )


class StructuredSettlementOption(BaseModel):
    """Structured settlement option for large BI claims.

    Periodic payments can provide tax advantages (IRC §104(a)(2)) and
    protect claimants in high-value settlements.
    """

    total_settlement: float = Field(..., ge=0, description="Total settlement amount")
    lump_sum_amount: float = Field(
        default=0, ge=0, description="Upfront lump sum (if any)"
    )
    periodic_payments: list[dict] = Field(
        default_factory=list,
        description="List of {amount, frequency, start_date, years} for periodic payments",
    )
    annuity_provider: Optional[str] = Field(
        default=None, description="Structured settlement annuity provider"
    )
    tax_qualified: bool = Field(
        default=True,
        description="Whether structure qualifies under IRC §104(a)(2)",
    )
    recommended_for_amount_over: float = Field(
        default=100_000,
        description="Threshold above which structured option is typically offered",
    )


class LossOfEarnings(BaseModel):
    """Loss of earnings / wage loss calculation."""

    pre_accident_income: Optional[float] = Field(
        default=None, ge=0, description="Pre-accident wage or income"
    )
    income_type: Optional[str] = Field(
        default=None, description="W-2, 1099, self-employed, etc."
    )
    days_missed: Optional[int] = Field(
        default=None, ge=0, description="Work days missed due to injury"
    )
    documented_amount: Optional[float] = Field(
        default=None, ge=0, description="Documented wage loss amount"
    )
    claimed_amount: Optional[float] = Field(
        default=None, ge=0, description="Amount claimed by claimant"
    )
    recommended_amount: Optional[float] = Field(
        default=None, ge=0, description="Recommended wage loss for settlement"
    )
    documentation_notes: Optional[str] = Field(
        default=None, description="Pay stubs, employer letter, tax returns"
    )
