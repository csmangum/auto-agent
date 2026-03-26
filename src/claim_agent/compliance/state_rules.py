"""State-specific compliance rules engine.

Loads applicable regulations per state (California, Florida, New York, Texas,
Georgia, New Jersey, Pennsylvania, Illinois) for:
- Prompt payment deadlines (days)
- Total loss thresholds (% of ACV)
- Diminished value requirements
- SIU referral thresholds
- Compliance deadline calculations for claim_tasks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from claim_agent.rag.constants import normalize_state


@dataclass
class StateRules:
    """State-specific compliance rules."""

    state: str
    prompt_payment_days: int
    """Days to pay first-party claims after acceptance (prompt payment statute)."""
    total_loss_threshold: float
    """Fraction of ACV (0.0-1.0) above which vehicle is declared total loss. E.g. 0.75 = 75%."""
    diminished_value_required: bool
    """Whether state mandates diminished value consideration (e.g. Georgia)."""
    diminished_value_formula: str | None
    """Formula key when DV is required (e.g. ``ga_17c``). ``None`` = generic percentage fallback."""
    siu_referral_threshold: int | None
    """Fraud score above which SIU referral is mandatory (None = no mandatory threshold)."""
    acknowledgment_days: int
    """Days to acknowledge claim receipt."""
    investigation_days: int
    """Days to complete investigation."""
    communication_response_days: int | None
    """Days to respond to claimant communications. None = no explicit state requirement."""
    appraisal_rights: bool
    """Whether policyholder has appraisal clause invocation rights."""
    comparative_fault_type: str
    """pure_comparative | modified_comparative_51 | contributory."""
    comparative_fault_bar: float | None
    """Fault % (0-100) above which insured cannot recover (e.g. 51 for 51% bar). None for pure comparative."""
    prompt_payment_base_date: Literal["fnol", "settlement_agreement"] = "settlement_agreement"
    """Base date for prompt-payment calculation: FNOL or settlement agreement date."""
    mandatory_indicators: list[str] = field(default_factory=list)
    """Fraud indicator codes that trigger mandatory SIU referral regardless of fraud score."""
    nicb_deadline_days_theft: int | None = None
    """Calendar days after incident to file NICB report for vehicle theft.
    Approximated from state working-day requirements (e.g. CA 5 working days ≈ 7 calendar days;
    NJ 2 working days ≈ 3 calendar days). None = no state-specific requirement; falls back to 30."""
    nicb_deadline_days_salvage: int | None = None
    """Calendar days after incident to file NICB report for salvage / total-loss transfers.
    None = no state-specific requirement; falls back to 30."""


# State-specific rules (California, Florida, New York, Texas, Georgia, New Jersey,
# Pennsylvania, Illinois)
# Based on typical regulatory requirements; RAG corpus provides detailed guidance.
_STATE_RULES: dict[str, StateRules] = {
    "California": StateRules(
        state="California",
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=40,
        communication_response_days=15,
        appraisal_rights=True,
        comparative_fault_type="pure_comparative",
        comparative_fault_bar=None,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging", "prior_siu_on_claimant"],
        # Cal. Ins. Code §1875.20: vehicle theft ≥$2k must be reported to NICB within 5 working days
        nicb_deadline_days_theft=7,   # 5 working days ≈ 7 calendar days
        nicb_deadline_days_salvage=30,
    ),
    "Florida": StateRules(
        state="Florida",
        prompt_payment_days=90,
        total_loss_threshold=0.80,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=80,
        acknowledgment_days=14,
        investigation_days=90,
        communication_response_days=14,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging", "prior_siu_on_claimant"],
        nicb_deadline_days_theft=30,
        nicb_deadline_days_salvage=30,
    ),
    "New York": StateRules(
        state="New York",
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=70,
        acknowledgment_days=15,
        investigation_days=30,
        communication_response_days=15,
        appraisal_rights=True,
        comparative_fault_type="pure_comparative",
        comparative_fault_bar=None,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging", "prior_siu_on_claimant"],
        nicb_deadline_days_theft=30,
        nicb_deadline_days_salvage=30,
    ),
    "Georgia": StateRules(
        state="Georgia",
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=True,
        diminished_value_formula="ga_17c",
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=30,
        communication_response_days=15,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=50.0,
        mandatory_indicators=["organized_fraud_ring"],
        nicb_deadline_days_theft=30,
        nicb_deadline_days_salvage=30,
    ),
    "Texas": StateRules(
        state="Texas",
        prompt_payment_days=30,
        total_loss_threshold=0.80,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=15,
        communication_response_days=15,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging"],
        nicb_deadline_days_theft=30,
        nicb_deadline_days_salvage=30,
    ),
    "New Jersey": StateRules(
        state="New Jersey",
        prompt_payment_days=30,
        total_loss_threshold=0.80,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=30,
        communication_response_days=15,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging", "prior_siu_on_claimant"],
        # NJSA 17:33A-15: vehicle theft must be reported to NICB within 2 working days
        nicb_deadline_days_theft=3,   # 2 working days ≈ 3 calendar days
        nicb_deadline_days_salvage=30,
    ),
    "Pennsylvania": StateRules(
        state="Pennsylvania",
        # 31 Pa. Code § 146.7: payment within 15 working days of settlement ≈ 30 calendar days
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=75,
        # 31 Pa. Code § 146.5(a)(4): acknowledge within 10 working days ≈ 14 calendar days
        acknowledgment_days=14,
        investigation_days=30,
        communication_response_days=15,
        appraisal_rights=True,
        # 42 Pa. C.S. § 7102: modified comparative – plaintiff barred if >50% at fault
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging", "prior_siu_on_claimant"],
        nicb_deadline_days_theft=30,
        nicb_deadline_days_salvage=30,
    ),
    "Illinois": StateRules(
        state="Illinois",
        # 50 Ill. Adm. Code 919: prompt payment 30 days after settlement agreement
        prompt_payment_days=30,
        # IL uses 80% ACV as the standard total-loss threshold
        total_loss_threshold=0.80,
        diminished_value_required=False,
        diminished_value_formula=None,
        siu_referral_threshold=75,
        # 50 Ill. Adm. Code 919.50(a): acknowledge within 10 working days ≈ 14 calendar days
        acknowledgment_days=14,
        # 50 Ill. Adm. Code 919.60: complete investigation within 45 days
        investigation_days=45,
        # 50 Ill. Adm. Code 919.50: respond to communications within 10 working days ≈ 14 calendar days
        communication_response_days=14,
        appraisal_rights=True,
        # 735 ILCS 5/2-1116: modified comparative – plaintiff barred if >50% at fault
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
        mandatory_indicators=["organized_fraud_ring", "bodily_injury_staging"],
        nicb_deadline_days_theft=30,
        nicb_deadline_days_salvage=30,
    ),
}


def get_state_rules(state: str | None) -> StateRules | None:
    """Return state-specific rules for the given state, or None if unsupported/missing."""
    if not state or not str(state).strip():
        return None
    try:
        normalized = normalize_state(str(state).strip())
        return _STATE_RULES.get(normalized)
    except ValueError:
        return None


def get_total_loss_threshold(state: str | None) -> float:
    """Return total loss threshold (0.0-1.0) for the state. Falls back to configured PARTIAL_LOSS_THRESHOLD if unknown."""
    rules = get_state_rules(state)
    if rules:
        return rules.total_loss_threshold
    from claim_agent.config.settings import get_settings
    return get_settings().partial_loss.threshold


def get_prompt_payment_days(state: str | None) -> int:
    """Return prompt payment deadline in days for the state. Default 30 if unknown."""
    rules = get_state_rules(state)
    return rules.prompt_payment_days if rules else 30


def get_prompt_payment_base_date(state: str | None) -> Literal["fnol", "settlement_agreement"]:
    """Return prompt-payment base date rule for the state.

    Most jurisdictions measure prompt-payment from settlement agreement/acceptance.
    Unknown states default to settlement_agreement while FNOL is still used as an
    initial estimate at claim intake.
    """
    rules = get_state_rules(state)
    return rules.prompt_payment_base_date if rules else "settlement_agreement"


def get_compliance_due_date(
    base_date: date,
    deadline_type: str,
    state: str | None,
) -> date | None:
    """Compute due date for a compliance deadline.

    Args:
        base_date: Reference date (e.g., claim receipt, acceptance date).
        deadline_type: One of: acknowledgment, investigation, prompt_payment.
        state: Loss state/jurisdiction.

    Returns:
        Due date or None if deadline_type not supported.
    """
    rules = get_state_rules(state)
    days: int | None = None
    if deadline_type == "acknowledgment":
        days = rules.acknowledgment_days if rules else 15
    elif deadline_type == "investigation":
        days = rules.investigation_days if rules else 40
    elif deadline_type == "prompt_payment":
        days = rules.prompt_payment_days if rules else 30
    elif deadline_type == "communication_response":
        days = rules.communication_response_days if rules else 15
    else:
        return None
    return None if days is None else base_date + timedelta(days=days)


def get_siu_referral_threshold(state: str | None) -> int | None:
    """Return mandatory SIU referral fraud score threshold, or None if no mandatory threshold."""
    rules = get_state_rules(state)
    return rules.siu_referral_threshold if rules else None


def get_mandatory_referral_indicators(state: str | None) -> list[str]:
    """Return indicator codes that trigger mandatory SIU referral regardless of score.

    Returns an empty list if the state has no indicator-based mandatory referral rules
    or if the state is unknown.
    """
    rules = get_state_rules(state)
    return list(rules.mandatory_indicators) if rules else []


def get_nicb_deadline_days(state: str | None, report_type: str = "theft") -> int:
    """Return the NICB filing deadline in calendar days for a given state and report type.

    Uses state-specific rules when available (e.g. CA vehicle theft: 5 working days ≈ 7 calendar
    days; NJ vehicle theft: 2 working days ≈ 3 calendar days). Falls back to 30 calendar days for
    states without a specific requirement or when ``state`` is unknown.

    Args:
        state: Loss state/jurisdiction (e.g. ``"California"`` or ``"CA"``).
        report_type: NICB report category – ``"theft"`` (default) or ``"salvage"``.

    Returns:
        Deadline expressed in calendar days from the incident date.
    """
    rules = get_state_rules(state)
    if rules is None:
        return 30
    if report_type == "salvage":
        days = rules.nicb_deadline_days_salvage
    else:
        days = rules.nicb_deadline_days_theft
    return days if days is not None else 30


def get_comparative_fault_rules(state: str | None) -> dict:
    """Return comparative fault rules for the state.

    Returns dict with:
    - comparative_fault_type: pure_comparative | modified_comparative_51 | contributory
    - comparative_fault_bar: float | None (percentage on 0–100 scale, e.g. 51.0 for 51% bar; None for pure comparative)
    - state: str | None
    """
    rules = get_state_rules(state)
    if not rules:
        return {
            "comparative_fault_type": "pure_comparative",
            "comparative_fault_bar": None,
            "state": None,
        }
    return {
        "comparative_fault_type": rules.comparative_fault_type,
        "comparative_fault_bar": rules.comparative_fault_bar,
        "state": rules.state,
    }


def is_recovery_eligible(liability_pct: float | None, state: str | None) -> bool:
    """Return True if subrogation recovery is eligible per state rules.

    - pure_comparative: always eligible (recovery reduced by fault %)
    - modified_comparative_51: eligible only if insured < 51% at fault
    - contributory: eligible only if insured 0% at fault
    """
    rules = get_state_rules(state)
    if not rules:
        return True
    if liability_pct is None:
        return True
    if rules.comparative_fault_type == "pure_comparative":
        return True
    if rules.comparative_fault_type == "contributory":
        return liability_pct <= 0.0
    if rules.comparative_fault_type == "modified_comparative_51" and rules.comparative_fault_bar is not None:
        return (liability_pct or 0) < rules.comparative_fault_bar
    return True
