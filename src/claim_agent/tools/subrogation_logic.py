"""Subrogation logic: liability assessment, case building, demand letters, recovery tracking."""

from __future__ import annotations

import datetime
import json
import logging

from claim_agent.db.database import get_db_path
from claim_agent.db.repository import ClaimRepository

logger = logging.getLogger(__name__)


# Use timezone-aware UTC for datetime (datetime.utcnow is deprecated)
def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


_NOT_AT_FAULT_KEYWORDS = [
    "rear-ended",
    "rear ended",
    "hit by",
    "hit from behind",
    "other driver",
    "third party",
    "not at fault",
    "not-at-fault",
    "struck by",
    "ran into",
    "ran red light",
    "ran stop sign",
    "drunk driver",
    "uninsured motorist",
    "hit and run",
    "parked car",
    "while parked",
    "side-swiped",
    "sideswiped",
]

_AT_FAULT_KEYWORDS = [
    "i hit",
    "i struck",
    "i ran",
    "my fault",
    "at fault",
    "rear-ended someone",
    "rear ended someone",
    "backed into",
    "collided with",
    "single vehicle",
    "lost control",
]


def assess_liability_impl(
    incident_description: str,
    claim_data_json: str = "",
    workflow_output: str = "",
) -> str:
    """Assess fault from incident description and claim context.

    Returns JSON with:
    - is_not_at_fault: bool
    - fault_determination: "not_at_fault" | "at_fault" | "unclear"
    - third_party_identified: bool
    - third_party_notes: str (if any)
    - reasoning: str
    """
    combined = f"{incident_description} {workflow_output}".lower()
    not_at_fault_score = sum(1 for kw in _NOT_AT_FAULT_KEYWORDS if kw in combined)
    at_fault_score = sum(1 for kw in _AT_FAULT_KEYWORDS if kw in combined)

    third_party_notes = ""
    if "other driver" in combined or "third party" in combined:
        third_party_notes = "Third party driver mentioned in incident description."
    elif "hit and run" in combined or "uninsured motorist" in combined:
        third_party_notes = "Third party may be unidentified or uninsured."

    if not_at_fault_score > at_fault_score:
        is_not_at_fault = True
        fault_determination = "not_at_fault"
        reasoning = f"Incident description indicates insured was not at fault (score: {not_at_fault_score} vs {at_fault_score})."
    elif at_fault_score > not_at_fault_score:
        is_not_at_fault = False
        fault_determination = "at_fault"
        reasoning = f"Incident description suggests insured may have been at fault (score: {at_fault_score} vs {not_at_fault_score})."
    else:
        is_not_at_fault = False
        fault_determination = "unclear"
        reasoning = "Insufficient information to determine fault; recommend manual review."

    third_party_identified = fault_determination == "not_at_fault" and bool(
        "other driver" in combined or "third party" in combined or "hit by" in combined
    )

    result = {
        "is_not_at_fault": is_not_at_fault,
        "fault_determination": fault_determination,
        "third_party_identified": third_party_identified,
        "third_party_notes": third_party_notes or None,
        "reasoning": reasoning,
    }
    return json.dumps(result)


def build_subrogation_case_impl(
    claim_id: str,
    payout_amount: float,
    liability_assessment: str,
    claim_data_json: str = "",
) -> str:
    """Build a subrogation recovery case from liability assessment and claim data.

    Returns JSON with case_id, claim_id, amount_sought, third_party_info, supporting_docs.
    """
    try:
        assessment = json.loads(liability_assessment)
    except (json.JSONDecodeError, TypeError):
        assessment = {}

    case_id = f"SUB-{claim_id}-001" if claim_id else "SUB-UNKNOWN-001"
    amount_sought = float(payout_amount) if payout_amount else 0.0

    third_party_info = {}
    if assessment.get("third_party_identified"):
        third_party_info = {
            "identified": True,
            "notes": assessment.get("third_party_notes", ""),
        }
    else:
        third_party_info = {"identified": False, "notes": "Third party not identified."}

    claim_data = {}
    if claim_data_json:
        try:
            claim_data = (
                json.loads(claim_data_json) if isinstance(claim_data_json, str) else claim_data_json
            )
        except json.JSONDecodeError:
            pass

    supporting_docs = [
        "Settlement documentation",
        "Payout record",
        "Liability assessment",
    ]
    if claim_data.get("incident_description"):
        supporting_docs.append("Incident description")

    liability_pct = assessment.get("liability_percentage") if assessment.get("liability_percentage") is not None else claim_data.get("liability_percentage")
    liability_basis = assessment.get("liability_basis") if assessment.get("liability_basis") is not None else claim_data.get("liability_basis")

    result = {
        "case_id": case_id,
        "claim_id": claim_id,
        "amount_sought": amount_sought,
        "third_party_info": third_party_info,
        "supporting_docs": supporting_docs,
        "status": "case_built",
    }
    if liability_pct is not None:
        result["liability_percentage"] = float(liability_pct)
    if liability_basis:
        result["liability_basis"] = str(liability_basis)

    # Persist to subrogation_cases table (idempotent: upsert by case_id)
    try:
        repo = ClaimRepository(get_db_path())
        existing = [r for r in repo.get_subrogation_cases_by_claim(claim_id) if r.get("case_id") == case_id]
        if existing:
            # Case already exists; no-op for create (or could update in future)
            pass
        else:
            repo.create_subrogation_case(
                claim_id=claim_id,
                case_id=case_id,
                amount_sought=amount_sought,
                liability_percentage=float(liability_pct) if liability_pct is not None else None,
                liability_basis=str(liability_basis) if liability_basis else None,
            )
    except Exception as e:
        logger.warning("Failed to persist subrogation case %s: %s", case_id, e)

    return json.dumps(result)


def send_demand_letter_impl(
    case_id: str,
    claim_id: str,
    amount_sought: float,
    third_party_info: str = "",
) -> str:
    """Generate and send demand letter to at-fault party (mock implementation).

    Returns JSON with confirmation, letter_id, sent_at.
    """
    letter_id = f"DEM-{case_id}-{_utc_now().strftime('%Y%m%d%H')}"
    sent_at = _utc_now().isoformat().replace("+00:00", "Z")

    result = {
        "confirmation": "Demand letter generated and sent (mock).",
        "letter_id": letter_id,
        "case_id": case_id,
        "claim_id": claim_id,
        "amount_sought": amount_sought,
        "sent_at": sent_at,
        "status": "demand_sent",
    }
    return json.dumps(result)


def record_arbitration_filing_impl(
    case_id: str,
    arbitration_forum: str = "Arbitration Forums Inc.",
    dispute_date: str = "",
) -> str:
    """Record that a subrogation dispute has been filed for arbitration.

    Returns JSON with confirmation.
    """
    from claim_agent.db.database import get_db_path
    from claim_agent.db.repository import ClaimRepository

    try:
        repo = ClaimRepository(get_db_path())
        repo.update_subrogation_case(
            case_id,
            arbitration_status="filed",
            arbitration_forum=arbitration_forum,
            dispute_date=dispute_date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        )
        return json.dumps({
            "confirmation": f"Arbitration filing recorded for case {case_id}",
            "case_id": case_id,
            "arbitration_forum": arbitration_forum,
            "arbitration_status": "filed",
        })
    except Exception as e:
        logger.warning("Failed to record arbitration filing for %s: %s", case_id, e)
        return json.dumps({
            "error": str(e),
            "case_id": case_id,
        })


def record_recovery_impl(
    claim_id: str,
    case_id: str,
    recovery_amount: float | None = None,
    recovery_status: str = "pending",
    notes: str = "",
) -> str:
    """Record recovery amount and status (mock implementation).

    recovery_status: pending | partial | full | closed_no_recovery
    """
    valid_statuses = ("pending", "partial", "full", "closed_no_recovery")
    if recovery_status not in valid_statuses:
        recovery_status = "pending"

    result = {
        "claim_id": claim_id,
        "case_id": case_id,
        "recovery_amount": recovery_amount,
        "recovery_status": recovery_status,
        "notes": notes or "",
        "recorded_at": _utc_now().isoformat().replace("+00:00", "Z"),
        "status": "recorded",
    }
    return json.dumps(result)
