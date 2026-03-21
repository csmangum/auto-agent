"""Bodily injury claim logic: medical records, injury severity, settlement calculation.

Mock implementations for query_medical_records, assess_injury_severity,
calculate_bi_settlement, PIP/MedPay exhaustion, CMS reporting, minor settlement,
structured settlement, loss of earnings, and medical bill auditing.
Real implementations would integrate with medical records systems (e.g., HIEs,
provider portals), policy systems, and CMS. TODO: Add MedicalRecordsAdapter for production.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from claim_agent.adapters.registry import get_cms_reporting_adapter, get_policy_adapter

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

# Structured settlement typically offered above this amount
STRUCTURED_SETTLEMENT_THRESHOLD = 100_000.0

# Default BI limits when policy does not specify
DEFAULT_BI_LIMIT_PER_PERSON = 250_000.0
DEFAULT_BI_LIMIT_PER_ACCIDENT = 500_000.0

# Charge thresholds for severity adjustment from medical records
SEVERE_CHARGE_THRESHOLD = 50_000.0
MODERATE_CHARGE_THRESHOLD = 10_000.0

# Settlement range (low, high) by severity for mock assess_injury_severity
SEVERITY_RANGES: dict[str, tuple[int, int]] = {
    "minor": (500, 5_000),
    "moderate": (5_000, 25_000),
    "severe": (25_000, 150_000),
    "catastrophic": (150_000, 1_000_000),
}

VALID_SEVERITIES = frozenset(("minor", "moderate", "severe", "catastrophic"))


def query_medical_records_impl(
    claim_id: str,
    claimant_id: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Query medical records associated with a bodily injury claim.

    Returns mock medical records summary. MOCK: Returns deterministic data
    varied by claim_id hash for test realism; production would integrate with
    medical records systems (e.g., HIEs, provider portals).
    """
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps(
            {
                "error": "Invalid claim_id",
                "records": [],
                "total_charges": None,
                "treatment_summary": None,
            }
        )
    # Mock response: vary total_charges by claim_id for test realism
    claim_hash = hash(claim_id) % 1000
    base_charges = 3750.0
    total_charges = base_charges + (claim_hash % 5) * 500
    return json.dumps(
        {
            "claim_id": claim_id,
            "claimant_id": claimant_id or "claimant-1",
            "records": [
                {
                    "provider": "Emergency Dept - General Hospital",
                    "date_of_service": "2024-01-15",
                    "diagnosis": "Whiplash, cervical strain",
                    "charges": 3500.00,
                    "treatment": "Exam, X-rays, pain management",
                },
                {
                    "provider": "Primary Care - Dr. Smith",
                    "date_of_service": "2024-01-20",
                    "diagnosis": "Follow-up, soft tissue injury",
                    "charges": 250.00,
                    "treatment": "Office visit, physical therapy referral",
                },
            ],
            "total_charges": total_charges,
            "treatment_summary": "Initial ER visit for cervical strain/whiplash; follow-up with PCP. No surgery or hospitalization.",
        }
    )


def assess_injury_severity_impl(
    injury_description: str,
    medical_records_json: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Assess injury severity based on description and medical records.

    Returns severity classification (minor, moderate, severe, catastrophic) with
    supporting factors. Real implementation could use medical coding or
    injury severity models.
    """
    if not injury_description or not isinstance(injury_description, str):
        return json.dumps(
            {
                "error": "Invalid injury_description",
                "severity": None,
                "factors": [],
                "recommended_range_low": None,
                "recommended_range_high": None,
            }
        )
    # Parse medical records if provided
    total_charges = None
    if medical_records_json:
        try:
            mr = json.loads(medical_records_json)
            total_charges = mr.get("total_charges")
        except (json.JSONDecodeError, TypeError):
            pass
    # Heuristic severity based on keywords and charges
    desc_lower = injury_description.lower()
    severity = "moderate"
    factors = []
    if any(k in desc_lower for k in ("death", "paralysis", "amputation", "brain injury")):
        severity = "catastrophic"
        factors.append("Catastrophic injury type indicated")
    elif any(k in desc_lower for k in ("fracture", "broken", "surgery", "hospitalization", "spinal")):
        severity = "severe"
        factors.append("Serious injury type indicated")
    elif any(k in desc_lower for k in ("minor", "bruise", "scratch", "soreness")):
        severity = "minor"
        factors.append("Minor injury description")
    else:
        factors.append("Soft tissue / moderate injury indicators")
    if total_charges is not None:
        factors.append(f"Total medical charges: ${total_charges:,.2f}")
        if total_charges > SEVERE_CHARGE_THRESHOLD:
            severity = "severe" if severity != "catastrophic" else severity
        elif total_charges > MODERATE_CHARGE_THRESHOLD:
            severity = "moderate" if severity == "minor" else severity
    low, high = SEVERITY_RANGES.get(severity, (5_000, 25_000))
    return json.dumps(
        {
            "severity": severity,
            "factors": factors,
            "recommended_range_low": low,
            "recommended_range_high": high,
            "total_medical_charges": total_charges,
        }
    )


def calculate_bi_settlement_impl(
    claim_id: str,
    policy_number: str,
    medical_charges: float,
    injury_severity: str,
    pain_suffering_multiplier: float = 1.5,
    loss_of_earnings: float = 0.0,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate proposed BI settlement within policy limits.

    Combines medical specials, optional documented loss of earnings (not
    multiplied for pain/suffering), and pain/suffering (multiplier applies to
    medical charges only). Returns ``economic_specials`` (medicals + LOE) and
    caps the total demand at policy BI per-person limits.
    """
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps(
            {
                "error": "Invalid claim_id",
                "proposed_settlement": None,
                "policy_bi_limit_per_person": None,
                "policy_bi_limit_per_accident": None,
            }
        )
    if not isinstance(medical_charges, (int, float)) or medical_charges < 0:
        return json.dumps(
            {
                "error": "Invalid medical_charges",
                "proposed_settlement": None,
                "policy_bi_limit_per_person": None,
                "policy_bi_limit_per_accident": None,
            }
        )
    loe = float(loss_of_earnings) if isinstance(loss_of_earnings, (int, float)) else 0.0
    if loe < 0:
        return json.dumps(
            {
                "error": "Invalid loss_of_earnings",
                "proposed_settlement": None,
                "policy_bi_limit_per_person": None,
                "policy_bi_limit_per_accident": None,
            }
        )
    # Get policy BI limits. CrewAI tools do not receive ctx, so get_policy_adapter()
    # is used when invoked from agents; ctx is only set when impl is called directly.
    policy_number = (policy_number or "").strip()
    bi_per_person = DEFAULT_BI_LIMIT_PER_PERSON
    bi_per_accident = DEFAULT_BI_LIMIT_PER_ACCIDENT
    if policy_number:
        adapter = ctx.adapters.policy if ctx else get_policy_adapter()
        try:
            policy = adapter.get_policy(policy_number)
            if policy:
                bi = policy.get("bodily_injury") or policy.get("bi_limits")
                if isinstance(bi, dict):
                    bi_per_person = float(bi.get("per_person", bi_per_person))
                    bi_per_accident = float(bi.get("per_accident", bi_per_accident))
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Policy lookup failed for BI limits: %s", exc)
    if injury_severity and injury_severity.lower() not in VALID_SEVERITIES:
        logger.warning(
            "Unexpected injury_severity %r; expected one of %s",
            injury_severity,
            sorted(VALID_SEVERITIES),
        )
    # Pain and suffering (multiplier on medical specials only); LOE is economic, not multiplied
    pain_suffering = float(medical_charges) * pain_suffering_multiplier
    economic_specials = float(medical_charges) + loe
    total_demand = economic_specials + pain_suffering
    # Cap at policy limit
    proposed = min(total_demand, bi_per_person)
    return json.dumps(
        {
            "claim_id": claim_id,
            "medical_charges": float(medical_charges),
            "loss_of_earnings": round(loe, 2),
            "economic_specials": round(economic_specials, 2),
            "injury_severity": injury_severity,
            "pain_suffering": round(pain_suffering, 2),
            "total_demand": round(total_demand, 2),
            "proposed_settlement": round(proposed, 2),
            "policy_bi_limit_per_person": bi_per_person,
            "policy_bi_limit_per_accident": bi_per_accident,
            "capped_by_limit": total_demand > bi_per_person,
        }
    )


def check_pip_medpay_exhaustion_impl(
    claim_id: str,
    policy_number: str,
    medical_charges: float,
    loss_state: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check whether PIP/MedPay is exhausted before BI settlement.

    In no-fault states (FL, NY, etc.), BI settlement typically requires
    PIP/MedPay exhaustion. Returns exhaustion status and whether BI can proceed.
    """
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps(
            {
                "error": "Invalid claim_id",
                "has_pip_medpay": False,
                "exhausted": False,
                "bi_settlement_allowed": False,
            }
        )
    # Mock: assume no-fault states (FL, NY) have PIP; others may have MedPay
    no_fault_states = ("FL", "NY", "NJ", "PA", "HI", "KS", "MA", "MI", "UT")
    # Map full state names to postal abbreviations
    state_name_to_abbr = {
        "FLORIDA": "FL",
        "NEW YORK": "NY",
        "NEW JERSEY": "NJ",
        "PENNSYLVANIA": "PA",
        "HAWAII": "HI",
        "KANSAS": "KS",
        "MASSACHUSETTS": "MA",
        "MICHIGAN": "MI",
        "UTAH": "UT",
    }
    state_input = (loss_state or "").strip().upper()
    # Check if input is full name or abbreviation
    state_upper = state_name_to_abbr.get(state_input, state_input[:2] if state_input else "")
    has_pip = state_upper in no_fault_states
    pip_limit = 10_000.0 if state_upper == "FL" else 50_000.0 if state_upper == "NY" else 2_500.0
    # Mock: treat as exhausted if medical charges >= limit or no PIP
    exhausted = has_pip and medical_charges >= pip_limit if has_pip else True
    bi_allowed = not has_pip or exhausted
    return json.dumps(
        {
            "claim_id": claim_id,
            "has_pip_medpay": has_pip,
            "pip_medpay_limit": pip_limit if has_pip else None,
            "amount_paid": min(medical_charges, pip_limit) if has_pip else None,
            "exhausted": exhausted,
            "bi_settlement_allowed": bi_allowed,
            "notes": f"State: {state_upper or 'unknown'}; "
            + ("PIP exhausted, BI may proceed" if bi_allowed else "PIP not exhausted"),
        }
    )


def check_cms_reporting_required_impl(
    claim_id: str,
    settlement_amount: float,
    claimant_medicare_eligible: bool = False,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check whether CMS/Medicare reporting is required (MMSEA Section 111).

    Delegates to :class:`~claim_agent.adapters.base.CMSReportingAdapter`.
    """
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps(
            {
                "error": "Invalid claim_id",
                "reporting_required": False,
            }
        )
    adapter = get_cms_reporting_adapter()
    if ctx is not None and getattr(ctx, "adapters", None) is not None:
        adapter = ctx.adapters.cms
    payload = adapter.evaluate_settlement_reporting(
        claim_id=claim_id,
        settlement_amount=float(settlement_amount),
        claimant_medicare_eligible=bool(claimant_medicare_eligible),
    )
    out = {"claim_id": claim_id, **payload}
    return json.dumps(out)


def check_minor_settlement_approval_impl(
    claim_id: str,
    claimant_age: int | None = None,
    claimant_incapacitated: bool = False,
    loss_state: str = "",
    court_approval_obtained: bool = False,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check whether court approval is required for minor/incapacitated claimant settlement."""
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps(
            {
                "error": "Invalid claim_id",
                "court_approval_required": False,
            }
        )
    is_minor = claimant_age is not None and claimant_age < 18
    approval_required = is_minor or claimant_incapacitated
    obtained = bool(court_approval_obtained)
    return json.dumps(
        {
            "claim_id": claim_id,
            "claimant_is_minor": is_minor,
            "claimant_age": claimant_age,
            "claimant_incapacitated": claimant_incapacitated,
            "court_approval_required": approval_required,
            "court_approval_obtained": obtained,
            "state": (loss_state or "").strip() or None,
            "notes": "Most states require court approval for minor settlements; "
            "guardian/conservator may need to petition.",
        }
    )


def get_structured_settlement_option_impl(
    claim_id: str,
    total_settlement: float,
    lump_sum_pct: float = 0.3,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Generate structured settlement option for large BI claims.

    Periodic payments can provide tax advantages (IRC §104(a)(2)).
    """
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps({"error": "Invalid claim_id", "recommended": False})
    lump_sum = total_settlement * max(0, min(1, lump_sum_pct))
    remainder = total_settlement - lump_sum
    recommended = total_settlement >= STRUCTURED_SETTLEMENT_THRESHOLD
    # Mock: 5-year structure for remainder
    annual = remainder / 5 if remainder > 0 else 0
    periodic = [
        {"amount": round(annual, 2), "frequency": "annual", "years": 5}
    ] if remainder > 0 else []
    return json.dumps(
        {
            "claim_id": claim_id,
            "total_settlement": total_settlement,
            "lump_sum_amount": round(lump_sum, 2),
            "periodic_payments": periodic,
            "recommended_for_amount_over": STRUCTURED_SETTLEMENT_THRESHOLD,
            "recommended": recommended,
            "tax_qualified": True,
        }
    )


def calculate_loss_of_earnings_impl(
    pre_accident_income: float,
    days_missed: int,
    income_type: str = "w2",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate loss of earnings from wage and days missed."""
    if pre_accident_income <= 0 or days_missed <= 0:
        return json.dumps(
            {
                "error": "Invalid input",
                "recommended_amount": 0,
                "documentation_required": True,
            }
        )
    # Assume ~260 work days/year for W-2
    daily_rate = pre_accident_income / 260 if income_type.lower() == "w2" else pre_accident_income / 365
    recommended = daily_rate * days_missed
    return json.dumps(
        {
            "pre_accident_income": pre_accident_income,
            "days_missed": days_missed,
            "daily_rate": round(daily_rate, 2),
            "recommended_amount": round(recommended, 2),
            "documentation_required": True,
            "notes": "Require pay stubs, employer letter, or tax returns.",
        }
    )


def audit_medical_bills_impl(
    medical_records_json: str,
    incident_date: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Audit medical bills for duplicates, excessive treatment, unrelated conditions.

    Returns audit findings: duplicate charges, excessive treatment, unrelated.
    """
    if not medical_records_json or not isinstance(medical_records_json, str):
        return json.dumps(
            {
                "error": "Invalid medical_records_json",
                "audit_findings": [],
                "total_allowed": None,
                "reduction_amount": 0,
            }
        )
    try:
        mr = json.loads(medical_records_json)
    except (json.JSONDecodeError, TypeError):
        return json.dumps(
            {
                "error": "Invalid JSON",
                "audit_findings": [],
                "total_allowed": None,
                "reduction_amount": 0,
            }
        )
    records = mr.get("records", [])
    total_billed = mr.get("total_charges") if mr.get("total_charges") is not None else sum(r.get("charges", 0) for r in records)
    findings: list[dict[str, Any]] = []
    total_allowed = 0.0
    for r in records:
        billed = float(r.get("charges", 0))
        # Mock: allow 85% of billed as reasonable
        allowed = billed * 0.85
        total_allowed += allowed
        if billed > 5000:
            findings.append(
                {
                    "provider": r.get("provider", "Unknown"),
                    "issue": "high_charge",
                    "billed": billed,
                    "recommended_allowed": round(allowed, 2),
                }
            )
    reduction = total_billed - total_allowed
    return json.dumps(
        {
            "total_billed": total_billed,
            "total_allowed": round(total_allowed, 2),
            "reduction_amount": round(reduction, 2),
            "audit_findings": findings,
            "notes": "Review for duplicate charges, excessive treatment, unrelated conditions.",
        }
    )


def build_treatment_timeline_impl(
    medical_records_json: str,
    incident_date: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Build treatment timeline from medical records for settlement valuation."""
    if not medical_records_json or not isinstance(medical_records_json, str):
        return json.dumps(
            {
                "error": "Invalid medical_records_json",
                "treatment_duration_days": None,
                "total_charges": 0,
            }
        )
    try:
        mr = json.loads(medical_records_json)
    except (json.JSONDecodeError, TypeError):
        return json.dumps(
            {"error": "Invalid JSON", "treatment_duration_days": None, "total_charges": 0}
        )
    records = mr.get("records", [])
    if not records:
        return json.dumps(
            {
                "incident_date": incident_date or None,
                "treatment_duration_days": 0,
                "total_charges": mr.get("total_charges", 0),
                "events": [],
            }
        )
    dates = []
    events = []
    for r in records:
        dos = r.get("date_of_service", "")
        dt = None
        try:
            if dos:
                dt = datetime.strptime(dos, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            dt = None
        if dt is not None:
            dates.append(dt)
        events.append(
            {
                "event_date": dos,
                "provider": r.get("provider", ""),
                "treatment_type": r.get("treatment", "Unknown"),
                "diagnosis": r.get("diagnosis"),
                "charges": float(r.get("charges", 0)),
            }
        )
    first = min(dates) if dates else None
    last = max(dates) if dates else None
    duration = (last - first).days if first and last else 0
    total = mr.get("total_charges") if mr.get("total_charges") is not None else sum(r.get("charges", 0) for r in records)
    return json.dumps(
        {
            "incident_date": incident_date or None,
            "first_treatment_date": first.isoformat() if first else None,
            "last_treatment_date": last.isoformat() if last else None,
            "treatment_duration_days": duration,
            "total_charges": float(total),
            "events": events,
        }
    )
