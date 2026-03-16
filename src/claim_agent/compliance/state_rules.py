"""State-specific compliance rules engine.

Loads applicable regulations per state (California, Florida, New York, Texas) for:
- Prompt payment deadlines (days)
- Total loss thresholds (% of ACV)
- Diminished value requirements
- SIU referral thresholds
- Compliance deadline calculations for claim_tasks
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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
    siu_referral_threshold: int | None
    """Fraud score above which SIU referral is mandatory (None = no mandatory threshold)."""
    acknowledgment_days: int
    """Days to acknowledge claim receipt."""
    investigation_days: int
    """Days to complete investigation."""
    appraisal_rights: bool
    """Whether policyholder has appraisal clause invocation rights."""
    comparative_fault_type: str
    """pure_comparative | modified_comparative_51 | contributory."""
    comparative_fault_bar: float | None
    """Fault % (0-100) above which insured cannot recover (e.g. 51 for 51% bar). None for pure comparative."""


# State-specific rules (California, Florida, New York, Texas)
# Based on typical regulatory requirements; RAG corpus provides detailed guidance.
_STATE_RULES: dict[str, StateRules] = {
    "California": StateRules(
        state="California",
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=False,
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=40,
        appraisal_rights=True,
        comparative_fault_type="pure_comparative",
        comparative_fault_bar=None,
    ),
    "Florida": StateRules(
        state="Florida",
        prompt_payment_days=90,
        total_loss_threshold=0.80,
        diminished_value_required=False,
        siu_referral_threshold=80,
        acknowledgment_days=14,
        investigation_days=90,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
    ),
    "New York": StateRules(
        state="New York",
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=False,
        siu_referral_threshold=70,
        acknowledgment_days=15,
        investigation_days=30,
        appraisal_rights=True,
        comparative_fault_type="pure_comparative",
        comparative_fault_bar=None,
    ),
    "Georgia": StateRules(
        state="Georgia",
        prompt_payment_days=30,
        total_loss_threshold=0.75,
        diminished_value_required=True,
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=30,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
    ),
    "Texas": StateRules(
        state="Texas",
        prompt_payment_days=30,
        total_loss_threshold=0.80,
        diminished_value_required=False,
        siu_referral_threshold=75,
        acknowledgment_days=15,
        investigation_days=15,
        appraisal_rights=True,
        comparative_fault_type="modified_comparative_51",
        comparative_fault_bar=51.0,
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
    else:
        return None
    return base_date + timedelta(days=days)


def get_siu_referral_threshold(state: str | None) -> int | None:
    """Return mandatory SIU referral fraud score threshold, or None if no mandatory threshold."""
    rules = get_state_rules(state)
    return rules.siu_referral_threshold if rules else None


def get_comparative_fault_rules(state: str | None) -> dict:
    """Return comparative fault rules for the state.

    Returns dict with:
    - comparative_fault_type: pure_comparative | modified_comparative_51 | contributory
    - comparative_fault_bar: float | None (e.g. 0.51 for 51% bar; None for pure comparative)
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
