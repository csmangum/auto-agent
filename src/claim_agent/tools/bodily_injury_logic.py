"""Bodily injury claim logic: medical records, injury severity, settlement calculation.

Mock implementations for query_medical_records, assess_injury_severity, and
calculate_bi_settlement. Real implementations would integrate with medical
records systems, injury assessment models, and policy BI limits.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from claim_agent.adapters.registry import get_policy_adapter

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

# Default BI limits when policy does not specify
DEFAULT_BI_LIMIT_PER_PERSON = 250_000.0
DEFAULT_BI_LIMIT_PER_ACCIDENT = 500_000.0


def query_medical_records_impl(
    claim_id: str,
    claimant_id: str = "",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Query medical records associated with a bodily injury claim.

    Returns mock medical records summary. Real implementation would integrate
    with medical records systems (e.g., HIEs, provider portals).
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
    # Mock response: typical BI claim medical records structure
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
            "total_charges": 3750.00,
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
        if total_charges > 50000:
            severity = "severe" if severity != "catastrophic" else severity
        elif total_charges > 10000:
            severity = "moderate" if severity == "minor" else severity
    # Suggested settlement ranges (mock)
    ranges = {
        "minor": (500, 5000),
        "moderate": (5000, 25000),
        "severe": (25000, 150000),
        "catastrophic": (150000, 1000000),
    }
    low, high = ranges.get(severity, (5000, 25000))
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
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate proposed BI settlement within policy limits.

    Combines medical specials with pain/suffering (multiplier method) and
    caps at policy BI limits. Real implementation would apply jurisdiction-
    specific rules and policy terms.
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
    # Get policy BI limits
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
        except Exception as exc:
            logger.warning("Policy lookup failed for BI limits: %s", exc)
    # Pain and suffering (multiplier on medicals)
    pain_suffering = medical_charges * pain_suffering_multiplier
    total_demand = medical_charges + pain_suffering
    # Cap at policy limit
    proposed = min(total_demand, bi_per_person)
    return json.dumps(
        {
            "claim_id": claim_id,
            "medical_charges": float(medical_charges),
            "injury_severity": injury_severity,
            "pain_suffering": round(pain_suffering, 2),
            "total_demand": round(total_demand, 2),
            "proposed_settlement": round(proposed, 2),
            "policy_bi_limit_per_person": bi_per_person,
            "policy_bi_limit_per_accident": bi_per_accident,
            "capped_by_limit": total_demand > bi_per_person,
        }
    )
